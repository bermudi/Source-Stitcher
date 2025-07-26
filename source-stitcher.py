import sys
import os
import logging
from pathlib import Path
from datetime import datetime
import pathspec
import stat
import traceback

# PyQt6 imports
from PyQt6 import QtCore, QtWidgets, QtGui

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# --- Helper Function for Ignore Patterns ---
def load_ignore_patterns(directory: Path) -> pathspec.PathSpec | None:
    """Loads ignore patterns from .gitignore in the specified directory."""
    gitignore_path = directory / ".gitignore"
    patterns = []
    if gitignore_path.is_file():
        try:
            with gitignore_path.open("r", encoding="utf-8", errors='ignore') as f:
                patterns.extend(f.readlines())
        except Exception as e:
            logging.warning(f"Could not read {gitignore_path}: {e}")

    if patterns:
        try:
            return pathspec.PathSpec.from_lines(pathspec.patterns.GitWildMatchPattern, patterns)
        except Exception as e:
            logging.error(f"Error parsing ignore patterns from {gitignore_path}: {e}")
            return None
    return None

# --- Shared utility functions ---
def is_binary_file(filepath: Path) -> bool:
    """Check if a file is likely binary by looking for null bytes."""
    CHUNK_SIZE = 1024
    try:
        with filepath.open('rb') as f:
            chunk = f.read(CHUNK_SIZE)
        return b'\0' in chunk
    except OSError as e:
        logging.warning(f"Could not read start of file {filepath} to check if binary: {e}")
        return True
    except Exception as e:
        logging.error(f"Unexpected error checking if file is binary {filepath}: {e}", exc_info=True)
        return True

def is_likely_text_file(filepath: Path) -> bool:
    """
    Detect if file is likely text based on name patterns and content.
    """
    # Known text filenames without extensions
    text_filenames = {
        'readme', 'license', 'licence', 'changelog', 'changes', 'authors', 
        'contributors', 'copying', 'install', 'news', 'todo', 'version', 
        'dockerfile', 'makefile', 'rakefile', 'gemfile', 'pipfile', 'procfile', 
        'vagrantfile', 'jenkinsfile', 'cname', 'notice', 'manifest', 'copyright'
    }
    
    # Check if it's a known text filename (case insensitive)
    if filepath.name.lower() in text_filenames:
        return not is_binary_file(filepath)
    
    # Dotfiles are often config files (but skip .git, .DS_Store, etc.)
    if filepath.name.startswith('.') and len(filepath.name) > 1:
        # Skip known binary or special dotfiles
        skip_dotfiles = {'.git', '.ds_store', '.pyc', '.pyo', '.pyd', '.so', '.dylib', '.dll'}
        if filepath.name.lower() not in skip_dotfiles:
            return not is_binary_file(filepath)
    
    # Files with no extension that aren't binary
    if not filepath.suffix:
        return not is_binary_file(filepath)
    
    # Files with unusual extensions that might be text
    possible_text_extensions = {
        '.ini', '.cfg', '.conf', '.config', '.properties', '.env', '.envrc',
        '.ignore', '.keep', '.gitkeep', '.npmignore', '.dockerignore',
        '.editorconfig', '.flake8', '.pylintrc', '.prettierrc', '.eslintrc',
        '.stylelintrc', '.babelrc', '.npmrc', '.yarnrc', '.nvmrc', '.ruby-version',
        '.python-version', '.node-version', '.terraform', '.tf', '.tfvars',
        '.ansible', '.playbook', '.vault', '.j2', '.jinja', '.jinja2',
        '.template', '.tmpl', '.tpl', '.mustache', '.hbs', '.handlebars'
    }
    
    if filepath.suffix.lower() in possible_text_extensions:
        return not is_binary_file(filepath)
    
    return False

def matches_file_type(filepath: Path, selected_extensions: list[str], all_language_extensions: dict) -> bool:
    """Check if file matches any selected file type categories."""
    if "*" in selected_extensions:
        return True
    
    file_ext = filepath.suffix.lower()
    filename = filepath.name.lower()
    
    # First check standard extension and filename matching for all selected categories except "*other*"
    for ext in selected_extensions:
        if ext == "*other*":
            continue  # Handle this separately below
        if ext.startswith('.'):
            # Extension match
            if file_ext == ext.lower():
                return True
        else:
            # Filename match (for files like requirements.txt, package.json)
            if filename == ext.lower():
                return True
    
    # Handle special "Other Text Files" category
    if "*other*" in selected_extensions:
        # Check if file doesn't match any other category but appears to be text
        matched_by_other_category = False
        
        for lang, exts in all_language_extensions.items():
            if lang == "Other Text Files":
                continue
            
            # Check for filename matches
            filename_matches = [ext for ext in exts if not ext.startswith('.')]
            name_matches = [ext for ext in filename_matches if filename == ext.lower()]
            if name_matches:
                matched_by_other_category = True
                break
            
            # Check for extension matches
            if file_ext in [ext.lower() for ext in exts if ext.startswith('.')]:
                matched_by_other_category = True
                break
        
        # If not matched by other categories, check if it's likely text
        if not matched_by_other_category:
            return is_likely_text_file(filepath)
    
    return False

# --- Worker Class for Background Processing ---
class GeneratorWorker(QtCore.QObject):
    """
    Worker object to perform file counting and concatenation in a separate thread.
    """
    pre_count_finished = QtCore.pyqtSignal(int)
    progress_updated = QtCore.pyqtSignal(int)
    status_updated = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(str, str)

    def __init__(self, selected_paths: list[Path], base_dir: Path, allowed_extensions: list[str], all_language_extensions: dict, base_ignore_spec: pathspec.PathSpec | None, script_path: Path | None):
        super().__init__()
        self.selected_paths = selected_paths
        self.base_dir = base_dir
        self.allowed_extensions = allowed_extensions
        self.all_language_extensions = all_language_extensions
        self.base_ignore_spec = base_ignore_spec
        self.script_path = script_path
        self._is_cancelled = False

    def cancel(self):
        """Signals the worker to stop processing."""
        self._is_cancelled = True
        logging.info("Cancellation requested for worker.")

    def get_file_content(self, filepath: Path) -> str | None:
        """
        Safely read the content of a non-binary text file using UTF-8 encoding.
        Returns None if the file is binary, cannot be read, or causes decoding errors.
        """
        if is_binary_file(filepath):
            logging.warning(f"Skipping binary file detected during read: {filepath.name}")
            return None
        try:
            content = filepath.read_text(encoding='utf-8', errors='strict')
            if not content.strip():  # Skip empty or whitespace-only files
                logging.info(f"Skipping empty file: {filepath.name}")
                return None
            return content
        except UnicodeDecodeError:
            logging.warning(f"Skipping file due to UTF-8 decoding error: {filepath.name}")
            return None
        except PermissionError:
            logging.warning(f"Skipping file due to permission error: {filepath.name}")
            return None
        except FileNotFoundError:
             logging.warning(f"Skipping file as it was not found (possibly deleted): {filepath.name}")
             return None
        except OSError as e:
             logging.warning(f"Skipping file due to OS error during read: {filepath.name} ({e})")
             return None
        except Exception as e:
            logging.error(f"Unexpected error reading file {filepath}: {e}", exc_info=True)
            return None

    def count_files_recursive(self, dir_path: Path, current_dir_ignore_spec: pathspec.PathSpec | None) -> int:
        """Recursively count processable files in a directory, respecting ignores."""
        count = 0
        if self._is_cancelled: return 0

        def walk_error_handler(error: OSError):
            logging.warning(f"Permission/OS error during counting walk below {dir_path}: {error}")

        for root, dirs, files in os.walk(dir_path, topdown=True, onerror=walk_error_handler, followlinks=False):
            if self._is_cancelled: return count
            root_path = Path(root)
            try:
                 root_relative_to_base = root_path.relative_to(self.base_dir)
                 root_relative_to_current = root_path.relative_to(dir_path)
            except ValueError:
                 logging.warning(f"Count: Could not make path relative during walk: {root_path}. Skipping subtree.")
                 dirs[:] = []
                 continue

            original_dirs = list(dirs)
            dirs[:] = [d for d in original_dirs if not d.startswith('.') and
                       (not self.base_ignore_spec or not self.base_ignore_spec.match_file(str(root_relative_to_base / d) + '/')) and
                       (not current_dir_ignore_spec or not current_dir_ignore_spec.match_file(str(root_relative_to_current / d) + '/'))
                      ]

            for file_name in files:
                if self._is_cancelled: return count
                if file_name.startswith('.'): continue

                count_path = root_path / file_name

                try:
                    st = count_path.lstat()
                    if not stat.S_ISREG(st.st_mode): continue
                except OSError: continue

                try:
                    rel_base = count_path.relative_to(self.base_dir)
                    rel_dir = count_path.relative_to(dir_path)
                except ValueError: continue

                if (self.base_ignore_spec and self.base_ignore_spec.match_file(str(rel_base))) or \
                   (current_dir_ignore_spec and current_dir_ignore_spec.match_file(str(rel_dir))):
                    continue

                if self.script_path and count_path.resolve() == self.script_path:
                    continue

                # Use the new matching logic
                if matches_file_type(count_path, self.allowed_extensions, self.all_language_extensions):
                    if not is_binary_file(count_path):
                        count += 1
        return count

    def process_directory_recursive(self, dir_path: Path, current_dir_ignore_spec: pathspec.PathSpec | None, output_content: list, files_processed_counter: list) -> None:
        """
        Recursively process directory for files, appending to output_content.
        Updates files_processed_counter[0] for progress tracking.
        """
        if self._is_cancelled: return

        def walk_error_handler(error: OSError):
            logging.warning(f"Permission/OS error during processing walk below {dir_path}: {error}")

        for root, dirs, files in os.walk(dir_path, topdown=True, onerror=walk_error_handler, followlinks=False):
            if self._is_cancelled: return
            root_path = Path(root)

            try:
                 root_relative_to_base = root_path.relative_to(self.base_dir)
                 root_relative_to_current = root_path.relative_to(dir_path)
            except ValueError:
                 logging.warning(f"Process: Could not make path relative during walk: {root_path}. Skipping subtree.")
                 dirs[:] = []
                 continue

            original_dirs = list(dirs)
            dirs[:] = [d for d in original_dirs if not d.startswith('.') and
                       (not self.base_ignore_spec or not self.base_ignore_spec.match_file(str(root_relative_to_base / d) + '/')) and
                       (not current_dir_ignore_spec or not current_dir_ignore_spec.match_file(str(root_relative_to_current / d) + '/'))
                      ]

            for file_name in files:
                if self._is_cancelled: return
                if file_name.startswith('.'): continue

                full_path = root_path / file_name

                try:
                    st = full_path.lstat()
                    if not stat.S_ISREG(st.st_mode): continue
                except OSError as e:
                    logging.warning(f"Could not stat file during process walk: {full_path}, error: {e}. Skipping.")
                    continue

                try:
                     relative_path_to_base = full_path.relative_to(self.base_dir)
                     relative_path_to_current = full_path.relative_to(dir_path)
                except ValueError:
                     logging.warning(f"Could not make file path relative during process walk: {full_path}. Skipping.")
                     continue

                if (self.base_ignore_spec and self.base_ignore_spec.match_file(str(relative_path_to_base))) or \
                   (current_dir_ignore_spec and current_dir_ignore_spec.match_file(str(relative_path_to_current))):
                    continue

                if self.script_path and full_path.resolve() == self.script_path:
                    continue

                # Use the new matching logic
                if not matches_file_type(full_path, self.allowed_extensions, self.all_language_extensions):
                    continue

                file_content = self.get_file_content(full_path)
                if file_content is None:
                    continue

                relative_path_output = relative_path_to_base
                ext = full_path.suffix[1:] if full_path.suffix else 'txt'
                output_content.append(f"\n--- File: {relative_path_output} ---")
                output_content.append(f"```{ext}")
                output_content.append(file_content)
                output_content.append("```\n")

                files_processed_counter[0] += 1

    @QtCore.pyqtSlot()
    def run(self):
        """Main execution method for the worker thread."""
        total_files = 0
        output_content = []
        error_message = ""
        processed_files_count = [0]
        current_progress = 0

        try:
            logging.info("Worker started: Counting files...")
            self.status_updated.emit("Counting files...")

            for path in self.selected_paths:
                if self._is_cancelled: break
                try:
                    st = path.lstat()
                    is_regular_file = stat.S_ISREG(st.st_mode)
                    is_regular_dir = stat.S_ISDIR(st.st_mode)
                    rel_path_str = ""
                    try:
                        rel_path_str = str(path.relative_to(self.base_dir))
                    except ValueError: pass

                    if is_regular_file:
                        if self.base_ignore_spec and self.base_ignore_spec.match_file(rel_path_str):
                            continue
                        if self.script_path and path.resolve() == self.script_path:
                            continue
                        if not path.name.startswith('.') and not is_binary_file(path):
                            if matches_file_type(path, self.allowed_extensions, self.all_language_extensions):
                                total_files += 1
                    elif is_regular_dir:
                        if self.base_ignore_spec and self.base_ignore_spec.match_file(rel_path_str + '/'):
                            continue
                        current_dir_ignore_spec = load_ignore_patterns(path)
                        total_files += self.count_files_recursive(path, current_dir_ignore_spec)

                except (OSError, ValueError) as e:
                    logging.warning(f"Cannot access or process {path} during pre-count: {e}")
                    continue

            if self._is_cancelled:
                logging.info("Worker cancelled during counting phase.")
                self.finished.emit("", "Operation cancelled.")
                return

            logging.info(f"Worker: Counted {total_files} potential files.")
            self.pre_count_finished.emit(total_files)

            if total_files == 0:
                 logging.info("Worker: No files to process.")
                 self.finished.emit("", "")
                 return

            logging.info("Worker: Starting file processing...")
            self.status_updated.emit("Processing...")

            total_files_for_progress = max(1, total_files)

            for path in self.selected_paths:
                if self._is_cancelled: break
                try:
                    st = path.lstat()
                    is_regular_file = stat.S_ISREG(st.st_mode)
                    is_regular_dir = stat.S_ISDIR(st.st_mode)
                    rel_path_base_str = ""
                    try:
                        rel_path_base_str = str(path.relative_to(self.base_dir))
                    except ValueError: pass

                    if is_regular_file:
                        if self.base_ignore_spec and self.base_ignore_spec.match_file(rel_path_base_str):
                            continue
                        if self.script_path and path.resolve() == self.script_path:
                            continue
                        if not matches_file_type(path, self.allowed_extensions, self.all_language_extensions):
                             continue

                        file_content = self.get_file_content(path)
                        if file_content is not None:
                            ext = path.suffix[1:] if path.suffix else 'txt'
                            output_content.append(f"\n--- File: {rel_path_base_str} ---")
                            output_content.append(f"```{ext}")
                            output_content.append(file_content)
                            output_content.append("```\n")
                            processed_files_count[0] += 1

                            new_progress = int((processed_files_count[0] / total_files_for_progress) * 100)
                            if new_progress > current_progress:
                                current_progress = new_progress
                                self.progress_updated.emit(current_progress)

                    elif is_regular_dir:
                        if self.base_ignore_spec and self.base_ignore_spec.match_file(rel_path_base_str + '/'):
                            continue
                        current_dir_ignore_spec = load_ignore_patterns(path)
                        start_count = processed_files_count[0]
                        self.process_directory_recursive(path, current_dir_ignore_spec, output_content, processed_files_count)
                        end_count = processed_files_count[0]

                        if end_count > start_count:
                            new_progress = int((end_count / total_files_for_progress) * 100)
                            if new_progress > current_progress:
                                current_progress = new_progress
                                self.progress_updated.emit(new_progress)

                except (OSError, ValueError) as e:
                     logging.error(f"Worker: Error processing item {path.name}: {e}")
                     continue
                except Exception as e:
                    logging.error(f"Worker: Unexpected error processing item {path.name}: {e}", exc_info=True)
                    error_message = f"Unexpected error during processing: {e}"
                    continue

            if self._is_cancelled:
                logging.info("Worker cancelled during processing phase.")
                self.finished.emit("", "Operation cancelled.")
                return

            if not error_message:
                 self.progress_updated.emit(100)

            logging.info("Worker finished processing.")
            final_content = '\n'.join(output_content)
            self.finished.emit(final_content, error_message if error_message else "")

        except Exception as e:
            logging.error(f"Critical error in worker run method: {e}", exc_info=True)
            detailed_error = traceback.format_exc()
            self.finished.emit("", f"Critical worker error: {e}\n{detailed_error}")

# --- Main Application Window ---
class FileConcatenator(QtWidgets.QMainWindow):
    """
    A PyQt6-based graphical application for concatenating multiple files with language filtering.
    """
    PATH_ROLE = QtCore.Qt.ItemDataRole.UserRole + 1
    LANGUAGE_ROLE = QtCore.Qt.ItemDataRole.UserRole + 2

    def __init__(self, working_dir: Path = None) -> None:
        super().__init__()
        self.initial_base_dir = (working_dir or Path.cwd()).resolve()
        self.working_dir = self.initial_base_dir
        self.setWindowTitle(f"SOTA Concatenator - [{self.working_dir.name}]")
        self.resize(700, 650)

        self.ignore_spec = load_ignore_patterns(self.working_dir)
        self.icon_provider = QtWidgets.QFileIconProvider()

        self.worker_thread = None
        self.worker = None
        self.is_generating = False

        # Updated comprehensive language extensions
        self.language_extensions = {
            "Python": [".py", ".pyw", ".pyx", ".pyi", "requirements.txt", "setup.py", "setup.cfg", "pyproject.toml", "pipfile"],
            "JavaScript/TypeScript": [".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", "package.json", "package-lock.json", "yarn.lock"],
            "Web Frontend": [".html", ".htm", ".css", ".scss", ".sass", ".less", ".vue", ".svelte", ".astro"],
            "Java/Kotlin": [".java", ".kt", ".kts", ".gradle", "pom.xml", "build.gradle", "gradle.properties"],
            "C/C++": [".c", ".cpp", ".cxx", ".cc", ".h", ".hpp", ".hxx", ".cmake", "makefile", "cmakelists.txt"],
            "C#/.NET": [".cs", ".fs", ".vb", ".csproj", ".fsproj", ".vbproj", ".sln"],
            "Ruby": [".rb", ".rake", ".gemspec", ".ru", "gemfile", "gemfile.lock", "rakefile"],
            "PHP": [".php", ".phtml", ".php3", ".php4", ".php5", "composer.json", "composer.lock"],
            "Go": [".go", ".mod", ".sum", "go.mod", "go.sum"],
            "Rust": [".rs", "cargo.toml", "cargo.lock"],
            "Swift/Objective-C": [".swift", ".m", ".mm", ".h", "package.swift", "podfile", "podfile.lock"],
            "Shell Scripts": [".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd"],
            "Config & Data": [
                ".json", ".yaml", ".yml", ".toml", ".xml", ".ini", ".cfg", ".conf", 
                ".config", ".properties", ".plist", ".env", ".envrc"
            ],
            "Documentation": [".md", ".markdown", ".rst", ".txt", ".adoc", ".org", "readme", "changelog", "license", "authors"],
            "DevOps & CI": [
                ".dockerfile", "dockerfile", ".dockerignore", "docker-compose.yml", "docker-compose.yaml",
                ".travis.yml", ".gitlab-ci.yml", ".github", ".circleci", ".appveyor.yml", 
                ".azure-pipelines.yml", "jenkinsfile", "vagrantfile", ".terraform", ".tf", ".tfvars"
            ],
            "Version Control": [".gitignore", ".gitattributes", ".gitmodules", ".gitkeep"],
            "Build & Package": [
                "makefile", ".ninja", ".bazel", ".buck", "build.gradle", "gradle.properties",
                "composer.json", "cargo.toml", "pipfile", "gemfile", "podfile", "package.json"
            ],
            "Other Text Files": ["*other*"]  # Special category for unmatched text files
        }

        self.init_ui()
        self.populate_file_tree() # Changed from populate_file_list

    def init_ui(self) -> None:
        """Create and place all PyQt6 widgets."""
        central_widget = QtWidgets.QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QtWidgets.QVBoxLayout(central_widget)

        # --- Top Layout ---
        top_nav_layout = QtWidgets.QHBoxLayout()
        self.btn_up = QtWidgets.QPushButton()
        self.btn_up.setIcon(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ArrowUp))
        self.btn_up.setToolTip("Go to Parent Directory (Alt+Up)")
        self.btn_up.setShortcut(QtGui.QKeySequence(QtCore.Qt.KeyboardModifier.AltModifier | QtCore.Qt.Key.Key_Up))
        self.btn_up.clicked.connect(self.go_up_directory)
        self.btn_up.setFixedWidth(self.btn_up.fontMetrics().horizontalAdvance(" Up ") * 2)
        top_nav_layout.addWidget(self.btn_up)

        self.current_path_label = QtWidgets.QLineEdit(str(self.working_dir))
        self.current_path_label.setReadOnly(True)
        self.current_path_label.setToolTip("Current Directory")
        top_nav_layout.addWidget(self.current_path_label)

        search_label = QtWidgets.QLabel("Search:")
        top_nav_layout.addWidget(search_label)
        self.search_entry = QtWidgets.QLineEdit()
        self.search_entry.setPlaceholderText("Filter items...")
        top_nav_layout.addWidget(self.search_entry)
        self.search_entry.textChanged.connect(self.refresh_files)
        top_nav_layout.addStretch()
        main_layout.addLayout(top_nav_layout)

        # --- Language Selection Section ---
        language_group = QtWidgets.QGroupBox("File Type Filters")
        language_layout = QtWidgets.QVBoxLayout(language_group)
        
        # Control buttons for language selection
        lang_buttons_layout = QtWidgets.QHBoxLayout()
        self.btn_select_all_languages = QtWidgets.QPushButton("All Types")
        self.btn_select_all_languages.clicked.connect(self.select_all_languages)
        self.btn_deselect_all_languages = QtWidgets.QPushButton("None")
        self.btn_deselect_all_languages.clicked.connect(self.deselect_all_languages)
        
        # Add common presets
        self.btn_code_only = QtWidgets.QPushButton("Code Only")
        self.btn_code_only.clicked.connect(self.select_code_only)
        self.btn_docs_config = QtWidgets.QPushButton("Docs & Config")
        self.btn_docs_config.clicked.connect(self.select_docs_config)
        
        lang_buttons_layout.addWidget(self.btn_select_all_languages)
        lang_buttons_layout.addWidget(self.btn_deselect_all_languages)
        lang_buttons_layout.addWidget(self.btn_code_only)
        lang_buttons_layout.addWidget(self.btn_docs_config)
        lang_buttons_layout.addStretch()
        language_layout.addLayout(lang_buttons_layout)

        # Language selection list
        self.language_list_widget = QtWidgets.QListWidget()
        self.language_list_widget.setMaximumHeight(140)
        self.language_list_widget.setAlternatingRowColors(True)
        
        # Populate language list with checkboxes
        for language_name in self.language_extensions.keys():
            item = QtWidgets.QListWidgetItem(language_name)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.CheckState.Checked)
            item.setData(self.LANGUAGE_ROLE, language_name)
            self.language_list_widget.addItem(item)
        
        self.language_list_widget.itemChanged.connect(self.refresh_files)
        language_layout.addWidget(self.language_list_widget)
        
        main_layout.addWidget(language_group)

        # --- File Tree Widget ---
        self.file_tree_widget = QtWidgets.QTreeWidget()
        self.file_tree_widget.setHeaderHidden(True)
        self.file_tree_widget.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_tree_widget.itemChanged.connect(self.on_tree_item_changed)
        self.file_tree_widget.itemDoubleClicked.connect(self.handle_tree_double_click)
        self.file_tree_widget.setAlternatingRowColors(True)
        main_layout.addWidget(self.file_tree_widget)

        # --- Bottom Layout ---
        bottom_layout = QtWidgets.QHBoxLayout()
        self.btn_select_all = QtWidgets.QPushButton("Select All Files")
        self.btn_select_all.clicked.connect(self.select_all)
        bottom_layout.addWidget(self.btn_select_all)

        self.btn_deselect_all = QtWidgets.QPushButton("Deselect All Files")
        self.btn_deselect_all.clicked.connect(self.deselect_all)
        bottom_layout.addWidget(self.btn_deselect_all)
        bottom_layout.addStretch()

        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setMinimumWidth(200)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        bottom_layout.addWidget(self.progress_bar)

        self.btn_cancel = QtWidgets.QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.cancel_generation)
        self.btn_cancel.setEnabled(False)
        bottom_layout.addWidget(self.btn_cancel)

        self.btn_generate = QtWidgets.QPushButton("Generate File")
        self.btn_generate.clicked.connect(self.start_generate_file)
        bottom_layout.addWidget(self.btn_generate)
        main_layout.addLayout(bottom_layout)

        self.update_ui_state()

    def get_selected_extensions(self) -> list[str]:
        """Get all file extensions from selected language types."""
        selected_extensions = []
        
        for i in range(self.language_list_widget.count()):
            item = self.language_list_widget.item(i)
            if item.checkState() == QtCore.Qt.CheckState.Checked:
                language_name = item.data(self.LANGUAGE_ROLE)
                if language_name in self.language_extensions:
                    selected_extensions.extend(self.language_extensions[language_name])
        
        # Remove duplicates and return
        return list(set(selected_extensions))

    def get_selected_language_names(self) -> list[str]:
        """Get names of selected language types for display purposes."""
        selected_names = []
        
        for i in range(self.language_list_widget.count()):
            item = self.language_list_widget.item(i)
            if item.checkState() == QtCore.Qt.CheckState.Checked:
                language_name = item.data(self.LANGUAGE_ROLE)
                selected_names.append(language_name)
        
        return selected_names

    def select_all_languages(self):
        """Select all language types."""
        if self.is_generating: return
        for i in range(self.language_list_widget.count()):
            item = self.language_list_widget.item(i)
            item.setCheckState(QtCore.Qt.CheckState.Checked)

    def deselect_all_languages(self):
        """Deselect all language types."""
        if self.is_generating: return
        for i in range(self.language_list_widget.count()):
            item = self.language_list_widget.item(i)
            item.setCheckState(QtCore.Qt.CheckState.Unchecked)

    def select_code_only(self):
        """Select only programming language categories."""
        if self.is_generating: return
        code_categories = {
            "Python", "JavaScript/TypeScript", "Web Frontend", "Java/Kotlin", 
            "C/C++", "C#/.NET", "Ruby", "PHP", "Go", "Rust", "Swift/Objective-C", "Shell Scripts"
        }
        for i in range(self.language_list_widget.count()):
            item = self.language_list_widget.item(i)
            language_name = item.data(self.LANGUAGE_ROLE)
            if language_name in code_categories:
                item.setCheckState(QtCore.Qt.CheckState.Checked)
            else:
                item.setCheckState(QtCore.Qt.CheckState.Unchecked)

    def select_docs_config(self):
        """Select documentation and configuration categories."""
        if self.is_generating: return
        docs_config_categories = {
            "Documentation", "Config & Data", "DevOps & CI", "Version Control", 
            "Build & Package", "Other Text Files"
        }
        for i in range(self.language_list_widget.count()):
            item = self.language_list_widget.item(i)
            language_name = item.data(self.LANGUAGE_ROLE)
            if language_name in docs_config_categories:
                item.setCheckState(QtCore.Qt.CheckState.Checked)
            else:
                item.setCheckState(QtCore.Qt.CheckState.Unchecked)

    def update_ui_state(self) -> None:
        """Updates UI elements based on the current state."""
        try:
            display_path = self.working_dir.relative_to(self.initial_base_dir)
            title_path = f".../{display_path}" if display_path != Path('.') else self.initial_base_dir.name
        except ValueError:
            title_path = str(self.working_dir)
        self.setWindowTitle(f"SOTA Concatenator - [{title_path}]")
        self.current_path_label.setText(str(self.working_dir))
        self.current_path_label.setCursorPosition(0)
        is_root = self.working_dir.parent == self.working_dir
        self.btn_up.setEnabled(not is_root and not self.is_generating)

    def set_controls_enabled(self, enabled: bool):
        """Enable/disable controls during generation."""
        self.btn_generate.setEnabled(enabled)
        self.btn_select_all.setEnabled(enabled)
        self.btn_deselect_all.setEnabled(enabled)
        self.btn_select_all_languages.setEnabled(enabled)
        self.btn_deselect_all_languages.setEnabled(enabled)
        self.btn_code_only.setEnabled(enabled)
        self.btn_docs_config.setEnabled(enabled)
        self.file_tree_widget.setEnabled(enabled) # Changed from file_list_widget
        self.language_list_widget.setEnabled(enabled)
        self.search_entry.setEnabled(enabled)
        is_root = self.working_dir.parent == self.working_dir
        self.btn_up.setEnabled(enabled and not is_root)
        self.btn_cancel.setEnabled(not enabled)

    # ↓ replace populate_file_list by populate_file_tree
    def populate_file_tree(self) -> None:
        """(Re)build the directory tree with check-boxes."""
        self.file_tree_widget.clear()

        selected_exts = self.get_selected_extensions()
        search_text    = self.search_entry.text().lower().strip()

        script_path = None
        if '__file__' in globals():
            try:
                script_path = Path(__file__).resolve()
            except Exception:
                pass

        root_item = QtWidgets.QTreeWidgetItem(self.file_tree_widget,
                                              [self.working_dir.name])
        root_item.setData(0, self.PATH_ROLE, self.working_dir)
        root_item.setFlags(root_item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
        root_item.setCheckState(0, QtCore.Qt.CheckState.Unchecked)
        self.build_subtree(root_item,
                           self.working_dir,
                           selected_exts,
                           search_text,
                           script_path)
        root_item.setExpanded(True)
        self.file_tree_widget.sortItems(0, QtCore.Qt.SortOrder.AscendingOrder)
        self.update_ui_state()

    def build_subtree(self,
                      parent_item: QtWidgets.QTreeWidgetItem,
                      parent_dir : Path,
                      selected_exts: list[str],
                      search_text : str,
                      script_path : Path | None):
        """Recursively attach children that pass filters."""
        try:
            entries = sorted(os.scandir(parent_dir),
                             key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            return
        for e in entries:
            p = Path(e.path)
            rel = p.relative_to(self.working_dir)
            ignore_name = str(rel) + ('/' if e.is_dir() else '')

            if self.ignore_spec and self.ignore_spec.match_file(ignore_name):
                continue
            if e.name.startswith('.') or (script_path and p.resolve()==script_path):
                continue
            if search_text and search_text not in e.name.lower():
                continue
            if e.is_symlink():
                continue

            if e.is_dir():
                dir_item = QtWidgets.QTreeWidgetItem(parent_item,[e.name])
                dir_item.setData(0, self.PATH_ROLE, p)
                dir_item.setFlags(dir_item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                dir_item.setCheckState(0, QtCore.Qt.CheckState.Unchecked)
                self.build_subtree(dir_item, p, selected_exts, search_text, script_path)
                # hide empty dirs
                if dir_item.childCount()==0:
                    parent_item.removeChild(dir_item)
            else:  # file
                if is_binary_file(p):
                    continue
                if selected_exts and not matches_file_type(p, selected_exts, self.language_extensions):
                    continue
                file_item = QtWidgets.QTreeWidgetItem(parent_item,[e.name])
                file_item.setData(0, self.PATH_ROLE, p)
                file_item.setFlags(file_item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                file_item.setCheckState(0, QtCore.Qt.CheckState.Unchecked)

    def on_tree_item_changed(self, item: QtWidgets.QTreeWidgetItem, column:int):
        if column != 0: 
            return
        
        state = item.checkState(0)
        
        # a) Propagate downwards
        def set_state_recursively(itm, st):
            for i in range(itm.childCount()):
                child = itm.child(i)
                # Disconnect to prevent recursive calls during state change
                self.file_tree_widget.itemChanged.disconnect(self.on_tree_item_changed)
                if child.flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable:
                    child.setCheckState(0, st)
                self.file_tree_widget.itemChanged.connect(self.on_tree_item_changed)
                set_state_recursively(child, st)  # Recursive call for sub-folders

        # Temporarily block signals to prevent re-triggering during downward propagation
        self.file_tree_widget.blockSignals(True)
        set_state_recursively(item, state)
        self.file_tree_widget.blockSignals(False)

        # b) Propagate upwards -- tristate logic
        def update_parent(ch):
            parent = ch.parent()
            if not parent: 
                return
            
            # Temporarily block signals for parent update
            self.file_tree_widget.itemChanged.disconnect(self.on_tree_item_changed)
            
            checked_children = 0
            unchecked_children = 0
            partial_children = 0
            total_checkable_children = 0

            for i in range(parent.childCount()):
                child = parent.child(i)
                if child.flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable:
                    total_checkable_children += 1
                    if child.checkState(0) == QtCore.Qt.CheckState.Checked:
                        checked_children += 1
                    elif child.checkState(0) == QtCore.Qt.CheckState.Unchecked:
                        unchecked_children += 1
                    elif child.checkState(0) == QtCore.Qt.CheckState.PartiallyChecked:
                        partial_children += 1
            
            if total_checkable_children == 0:  # Parent has no checkable children
                parent.setCheckState(0, QtCore.Qt.CheckState.Unchecked)
            elif checked_children == total_checkable_children:
                parent.setCheckState(0, QtCore.Qt.CheckState.Checked)
            elif unchecked_children == total_checkable_children:
                parent.setCheckState(0, QtCore.Qt.CheckState.Unchecked)
            else:
                parent.setCheckState(0, QtCore.Qt.CheckState.PartiallyChecked)
            
            self.file_tree_widget.itemChanged.connect(self.on_tree_item_changed)
            update_parent(parent)
        
        # Start upwards propagation after downward is done
        update_parent(item)

    def go_up_directory(self) -> None:
        """Navigate to the parent directory."""
        if self.is_generating:
            return
        
        parent_dir = self.working_dir.parent
        if parent_dir != self.working_dir:  # Not at filesystem root
            try:
                # Check if parent directory is accessible
                _ = list(os.scandir(parent_dir))
                self.working_dir = parent_dir.resolve()
                logging.info(f"Navigated up to directory: {self.working_dir}")
                self.search_entry.clear()
                self.refresh_files()
            except PermissionError:
                logging.warning(f"Permission denied trying to navigate to parent {parent_dir}")
                QtWidgets.QMessageBox.warning(self, "Access Denied", f"Cannot access parent directory:\n{parent_dir}\n\nPermission denied.")
            except FileNotFoundError:
                logging.warning(f"Parent directory not found: {parent_dir}")
                QtWidgets.QMessageBox.warning(self, "Not Found", f"Parent directory not found:\n{parent_dir}")
            except Exception as e:
                logging.error(f"Error navigating to parent directory {parent_dir}: {e}", exc_info=True)
                QtWidgets.QMessageBox.warning(self, "Navigation Error", f"Could not access parent directory:\n{parent_dir}\n\n{e}")

    def handle_tree_double_click(self, item: QtWidgets.QTreeWidgetItem, column:int):
        if self.is_generating: return
        path = item.data(0, self.PATH_ROLE)
        if path and path.is_dir():
            # Check if directory is accessible before changing working_dir
            try:
                _ = list(os.scandir(path))
                self.working_dir = path.resolve()
                logging.info(f"Navigated into directory: {self.working_dir}")
                self.search_entry.clear()
                self.refresh_files() # now rebuilds the tree
            except PermissionError:
                 logging.warning(f"Permission denied trying to navigate into {path}")
                 QtWidgets.QMessageBox.warning(self, "Access Denied", f"Cannot open directory:\n{path.name}\n\nPermission denied.")
            except FileNotFoundError:
                 logging.warning(f"Directory not found (deleted?) on double click: {path}")
                 QtWidgets.QMessageBox.warning(self, "Not Found", f"Directory not found:\n{path.name}")
                 self.refresh_files() # Refresh to update view if directory is gone
            except Exception as e:
                 logging.error(f"Error navigating into directory {path}: {e}", exc_info=True)
                 QtWidgets.QMessageBox.warning(self, "Navigation Error", f"Could not open directory:\n{path.name}\n\n{e}")

    # called from buttons or filters
    def refresh_files(self):
        """Refresh list (reload ignores)."""
        if self.is_generating: return
        self.ignore_spec = load_ignore_patterns(self.working_dir)
        self.populate_file_tree() # Changed from populate_file_list

    def collect_checked_paths(self) -> list[Path]:
        paths=[]
        def recurse(item):
            # Only add if it's a file or a fully checked directory
            # If it's a directory, the worker will recursively process it.
            # If it's a file, add it directly.
            p=item.data(0,self.PATH_ROLE)
            if p:
                if p.is_file() and item.checkState(0) == QtCore.Qt.CheckState.Checked:
                    paths.append(p)
                elif p.is_dir() and item.checkState(0) == QtCore.Qt.CheckState.Checked:
                    paths.append(p) # Add directory if fully checked

            # Continue recursion for all children, regardless of parent's check state
            # This ensures individual files/sub-folders selected within a partially checked folder are collected.
            for i in range(item.childCount()):
                recurse(item.child(i))
        
        for i in range(self.file_tree_widget.topLevelItemCount()):
            recurse(self.file_tree_widget.topLevelItem(i))
        return paths

    def select_all(self) -> None:
        """Select all checkable items."""
        if self.is_generating: return
        self.set_tree_state(QtCore.Qt.CheckState.Checked)

    def deselect_all(self) -> None:
        """Deselect all checkable items."""
        if self.is_generating: return
        self.set_tree_state(QtCore.Qt.CheckState.Unchecked)

    def set_tree_state(self, st):
        """Sets the check state of all items in the tree."""
        # Temporarily block signals to prevent itemChanged from firing for every item
        self.file_tree_widget.blockSignals(True) 
        def recurse(item):
            if item.flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(0, st)
            for i in range(item.childCount()):
                recurse(item.child(i))
        for i in range(self.file_tree_widget.topLevelItemCount()):
            recurse(self.file_tree_widget.topLevelItem(i))
        self.file_tree_widget.blockSignals(False)
        # Manually trigger a refresh for the top-level items to update their state visually if needed
        # (though on_tree_item_changed handles propagation, this ensures the root state is correct)
        for i in range(self.file_tree_widget.topLevelItemCount()):
            item = self.file_tree_widget.topLevelItem(i)
            # Trigger itemChanged for the root item to ensure propagation logic applies
            self.on_tree_item_changed(item, 0)


    def start_generate_file(self) -> None:
        """Initiates the file generation process in a background thread."""
        if self.is_generating:
            logging.warning("Generation process already running.")
            return

        selected_extensions = self.get_selected_extensions()
        if not selected_extensions:
            QtWidgets.QMessageBox.warning(self, "No File Types", "Please select at least one file type.")
            return

        selected_paths = self.collect_checked_paths() # Changed to use collect_checked_paths()

        if not selected_paths:
            QtWidgets.QMessageBox.warning(self, "No Selection", "Please tick at least one file or directory.") # Updated message
            return

        self.is_generating = True
        self.set_controls_enabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setFormat("Starting...")

        script_path = Path(__file__).resolve() if '__file__' in globals() else None

        self.worker_thread = QtCore.QThread()
        self.worker = GeneratorWorker(
            selected_paths=selected_paths,
            base_dir=self.working_dir,
            allowed_extensions=selected_extensions,
            all_language_extensions=self.language_extensions,
            base_ignore_spec=self.ignore_spec,
            script_path=script_path
        )
        self.worker.moveToThread(self.worker_thread)

        self.worker.pre_count_finished.connect(self.handle_pre_count)
        self.worker.progress_updated.connect(self.handle_progress_update)
        self.worker.status_updated.connect(self.handle_status_update)
        self.worker.finished.connect(self.handle_generation_finished)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.finished.connect(self.generation_cleanup)

        logging.info("Starting generator thread...")
        self.worker_thread.start()

    @QtCore.pyqtSlot(int)
    def handle_pre_count(self, total_files: int):
        """Slot to handle the pre_count_finished signal."""
        logging.info(f"Received pre-count: {total_files}")
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")

    @QtCore.pyqtSlot(int)
    def handle_progress_update(self, value: int):
        """Slot to handle the progress_updated signal."""
        self.progress_bar.setValue(value)

    @QtCore.pyqtSlot(str)
    def handle_status_update(self, message: str):
        """Slot to handle the status_updated signal."""
        self.progress_bar.setFormat(message + " %p%")

    @QtCore.pyqtSlot(str, str)
    def handle_generation_finished(self, result_content: str, error_message: str):
        """Slot to handle the finished signal from the worker."""
        logging.info(f"Generator worker finished. Error: '{error_message}'")

        if not error_message:
            self.progress_bar.setValue(100)
            self.progress_bar.setFormat("Finalizing...")
        elif "cancel" in error_message.lower():
             self.progress_bar.setFormat("Cancelled")
        else:
             self.progress_bar.setFormat("Error")

        if error_message:
            if "cancel" not in error_message.lower():
                 QtWidgets.QMessageBox.warning(self, "Generation Error", f"An error occurred:\n{error_message}")
        elif not result_content:
            QtWidgets.QMessageBox.information(self, "Finished", "No processable content found in the selected items matching the filters.")
        else:
            self.save_generated_file(result_content)

    def generation_cleanup(self):
        """Slot called when the thread finishes, regardless of reason."""
        logging.info("Generator thread finished signal received. Cleaning up.")
        self.worker = None
        self.worker_thread = None
        self.is_generating = False
        self.set_controls_enabled(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")

    def cancel_generation(self):
        """Requests cancellation of the running worker."""
        if self.worker:
            logging.info("Cancel button clicked. Requesting worker cancellation.")
            self.worker.cancel()
            self.btn_cancel.setEnabled(False)
            self.progress_bar.setFormat("Cancelling...")
        else:
            logging.warning("Cancel clicked but no worker active.")

    def save_generated_file(self, content: str):
        """Handles the save file dialog and writing the output."""
        # Try to find Desktop, with multiple fallback strategies
        desktop_path = None
        possible_desktop_paths = [
            Path.home() / "Desktop",
            Path.home() / "desktop",  # Linux sometimes uses lowercase
            Path.home() / "Bureau",   # French systems
            Path.home() / "Escritorio",  # Spanish systems
            Path.home() / "Área de Trabalho",  # Portuguese systems
        ]
        
        for path in possible_desktop_paths:
            if path.exists() and path.is_dir():
                desktop_path = path
                break
        
        # Fallback to home directory if no desktop found
        if not desktop_path:
            desktop_path = Path.home()
            logging.info("Desktop directory not found, using home directory as default")
        
        # Generate filename based on the current working directory name
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Use the actual directory name being processed
        dir_name = self.working_dir.name if self.working_dir.name else "files"
        
        # Include selected language types in filename (abbreviated)
        selected_langs = self.get_selected_language_names()
        if len(selected_langs) == len(self.language_extensions):
            lang_suffix = "all_types"
        elif len(selected_langs) <= 2:
            lang_suffix = "_".join(selected_langs)
        elif len(selected_langs) <= 4:
            lang_suffix = "_".join(selected_langs[:3]) + "_etc"
        else:
            lang_suffix = "mixed_types"
        
        # Clean up language suffix for filename (remove problematic characters)
        lang_suffix = lang_suffix.replace("/", "_").replace("&", "and").replace(" ", "_")
        
        initial_filename = f"{dir_name}_{lang_suffix}_{timestamp}.md"
        
        # Ensure filename is not too long (some filesystems have limits)
        if len(initial_filename) > 100:
            initial_filename = f"concatenated_{dir_name}_{timestamp}.md"
        
        default_path = desktop_path / initial_filename
        
        logging.info(f"Save dialog defaulting to: {default_path}")
        
        file_tuple = QtWidgets.QFileDialog.getSaveFileName(
            self, 
            "Save Concatenated File", 
            str(default_path),  # This sets both directory and filename
            "Markdown Files (*.md);;Text Files (*.txt);;All Files (*)"
        )
        output_filename = file_tuple[0]

        if not output_filename:
            logging.info("Save operation cancelled by user.")
            QtWidgets.QMessageBox.information(self, "Cancelled", "Save operation cancelled.")
            return

        try:
            output_path = Path(output_filename)
            
            # Prevent overwriting the running script
            if '__file__' in globals() and output_path.resolve() == Path(__file__).resolve():
                QtWidgets.QMessageBox.critical(self, "Error", "Cannot overwrite the running script file!")
                return

            # Create the output content with better header information
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(f"# Concatenated Files from: {self.working_dir}\n")
                f.write(f"# Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"# Total directory size: {self.working_dir.name}\n")
                
                # Show selected file types in a readable format
                selected_types = self.get_selected_language_names()
                if len(selected_types) == len(self.language_extensions):
                    f.write("# Selected file types: All types\n")
                else:
                    f.write(f"# Selected file types: {', '.join(selected_types)}\n")
                
                # Add some statistics if we can calculate them quickly
                try:
                    file_count = len([item for item in content.split('\n--- File:') if item.strip()])
                    f.write(f"# Number of files included: {file_count}\n")
                except:
                    pass
                
                f.write("\n" + "="*60 + "\n")
                f.write("START OF CONCATENATED CONTENT\n")
                f.write("="*60 + "\n\n")
                f.write(content)
                f.write("\n" + "="*60 + "\n")
                f.write("END OF CONCATENATED CONTENT\n")
                f.write("="*60 + "\n")
            
            # Success message with file location
            QtWidgets.QMessageBox.information(
                self, 
                "Success", 
                f"File generated successfully!\n\nSaved to:\n{output_filename}\n\nFile size: {output_path.stat().st_size:,} bytes"
            )
            logging.info(f"Successfully generated file: {output_filename}")
            
        except Exception as e:
            logging.error(f"Error writing output file {output_filename}: {e}", exc_info=True)
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Could not write output file:\n{output_filename}\n\n{e}"
            )
        finally:
            # Reset progress bar
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("%p%")


    def closeEvent(self, event: QtGui.QCloseEvent):
        """Handle window close event, ensuring worker thread is stopped."""
        if self.is_generating and self.worker_thread and self.worker_thread.isRunning():
            reply = QtWidgets.QMessageBox.question(self, 'Confirm Exit',
                                                   "A generation task is running. Are you sure you want to exit?",
                                                   QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                                                   QtWidgets.QMessageBox.StandardButton.No)
            if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                logging.info("Window close requested during generation. Attempting cancellation.")
                if self.worker:
                    self.worker.cancel()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

if __name__ == "__main__":
    QtCore.QCoreApplication.setApplicationName("SOTA Concatenator")
    QtCore.QCoreApplication.setOrganizationName("YourOrg")
    QtCore.QCoreApplication.setApplicationVersion("1.4-fixed")

    app = QtWidgets.QApplication(sys.argv)

    settings = QtCore.QSettings("YourOrg", "SOTAConcatenator")
    last_dir = settings.value("last_directory", str(Path.cwd()))

    selected_dir = QtWidgets.QFileDialog.getExistingDirectory(
        None, "Select Project Directory To Concatenate", last_dir
    )

    if selected_dir:
        working_dir = Path(selected_dir)
        settings.setValue("last_directory", selected_dir)
    else:
        logging.warning("No directory selected on startup. Exiting.")
        sys.exit(0)

    window = FileConcatenator(working_dir=working_dir)
    window.show()
    sys.exit(app.exec())