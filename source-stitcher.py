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

def build_filter_sets(ext_dict: dict[str, list[str]]) -> tuple[set[str], set[str]]:
    """Compiles all known extensions and filenames into sets for quick lookup."""
    by_ext, by_name = set(), set()
    for exts in ext_dict.values():
        for e in exts:
            (by_ext if e.startswith('.') else by_name).add(e.lower())
    return by_ext, by_name

def matches_file_type(
    filepath: Path,
    selected_exts: set[str],
    selected_names: set[str],
    all_exts: set[str],
    all_names: set[str],
    handle_other: bool
) -> bool:
    """Check if a file path matches the compiled filter sets."""
    file_ext = filepath.suffix.lower()
    file_name = filepath.name.lower()

    if file_name in selected_names:
        return True
    if file_ext in selected_exts:
        return True

    # Handle "Other Text Files" logic
    if handle_other:
        # Check if the file does NOT match any of the known file types
        if file_name not in all_names and file_ext not in all_exts:
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

    def __init__(
        self,
        selected_paths: list[Path],
        base_dir: Path,
        selected_exts: set[str],
        selected_names: set[str],
        all_exts: set[str],
        all_names: set[str],
        handle_other: bool,
        base_ignore_spec: pathspec.PathSpec | None,
        script_path: Path | None
    ):
        super().__init__()
        self.selected_paths = selected_paths
        self.base_dir = base_dir
        self.selected_exts = selected_exts
        self.selected_names = selected_names
        self.all_exts = all_exts
        self.all_names = all_names
        self.handle_other = handle_other
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
             logging.warning(f"Skipping file as it was not found (possibly deleted?): {filepath.name}")
             return None
        except OSError as e:
             logging.warning(f"Skipping file due to OS error during read: {filepath.name} ({e})")
             return None
        except Exception as e:
            logging.error(f"Unexpected error reading file {filepath}: {e}", exc_info=True)
            return None


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
                if not matches_file_type(full_path, self.selected_exts, self.selected_names, self.all_exts, self.all_names, self.handle_other):
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
        output_content = []
        error_message = ""
        files_processed_count = 0

        # Estimate total files for progress bar. This is a rough guess.
        # A full pre-count is avoided for performance.
        estimated_total_files = 0
        for path in self.selected_paths:
            if path.is_file():
                estimated_total_files += 1
            elif path.is_dir():
                try:
                    # Quick, non-recursive estimate
                    estimated_total_files += len([e for e in os.scandir(path) if e.is_file() and not e.name.startswith('.')])
                except OSError:
                    pass # Ignore permission errors here

        self.pre_count_finished.emit(estimated_total_files if estimated_total_files > 0 else 100) # Fake max for progress
        self.status_updated.emit("Processing...")

        try:
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

                        if matches_file_type(path, self.selected_exts, self.selected_names, self.all_exts, self.all_names, self.handle_other):
                            file_content = self.get_file_content(path)
                            if file_content is not None:
                                ext = path.suffix[1:] if path.suffix else 'txt'
                                output_content.append(f"\n--- File: {rel_path_base_str} ---")
                                output_content.append(f"```{ext}")
                                output_content.append(file_content)
                                output_content.append("```\n")
                                files_processed_count += 1
                                if estimated_total_files > 0:
                                    progress = int((files_processed_count / estimated_total_files) * 100)
                                    self.progress_updated.emit(min(progress, 99)) # Keep it below 100 until the end

                    elif is_regular_dir:
                        if self.base_ignore_spec and self.base_ignore_spec.match_file(rel_path_base_str + '/'):
                            continue

                        current_dir_ignore_spec = load_ignore_patterns(path)
                        # We pass a list to process_directory_recursive so it can be mutated
                        processed_counter_ref = [files_processed_count]
                        self.process_directory_recursive(path, current_dir_ignore_spec, output_content, processed_counter_ref)

                        # Update progress based on the mutated counter
                        newly_processed = processed_counter_ref[0] - files_processed_count
                        if newly_processed > 0:
                            files_processed_count = processed_counter_ref[0]
                            if estimated_total_files > 0:
                                progress = int((files_processed_count / estimated_total_files) * 100)
                                self.progress_updated.emit(min(progress, 99))

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

            logging.info(f"Worker finished processing. Total files included: {files_processed_count}")
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

        # Pre-compile all known extensions and filenames for fast lookups
        self.ALL_EXTENSIONS, self.ALL_FILENAMES = build_filter_sets(self.language_extensions)

        self.init_ui()
        self.populate_file_list()

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
        self.file_tree_widget.setHeaderLabels(["Name"])
        self.file_tree_widget.setColumnCount(1)
        self.file_tree_widget.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_tree_widget.itemDoubleClicked.connect(self.handle_item_double_click)
        self.file_tree_widget.itemExpanded.connect(self.populate_children)
        self.file_tree_widget.setAlternatingRowColors(True)
        main_layout.addWidget(self.file_tree_widget)

        # --- Bottom Layout ---
        bottom_layout = QtWidgets.QHBoxLayout()
        self.btn_select_all = QtWidgets.QPushButton("Select All")
        self.btn_select_all.clicked.connect(self.select_all)
        bottom_layout.addWidget(self.btn_select_all)

        self.btn_deselect_all = QtWidgets.QPushButton("Deselect All")
        self.btn_deselect_all.clicked.connect(self.deselect_all)
        bottom_layout.addWidget(self.btn_deselect_all)
        bottom_layout.addStretch()

        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setMinimumWidth(200)
        self.btn_code_only.clicked.connect(self.select_code_only)
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

    def get_selected_filter_sets(self) -> tuple[set[str], set[str], bool]:
        """Get the compiled sets of selected extensions and filenames."""
        selected_exts, selected_names = set(), set()
        handle_other = False

        for i in range(self.language_list_widget.count()):
            item = self.language_list_widget.item(i)
            if item.checkState() == QtCore.Qt.CheckState.Checked:
                language_name = item.data(self.LANGUAGE_ROLE)
                if language_name == "Other Text Files":
                    handle_other = True
                    continue

                if language_name in self.language_extensions:
                    for e in self.language_extensions[language_name]:
                        (selected_exts if e.startswith('.') else selected_names).add(e.lower())

        return selected_exts, selected_names, handle_other

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
        self.file_tree_widget.setEnabled(enabled)
        self.language_list_widget.setEnabled(enabled)
        self.search_entry.setEnabled(enabled)
        is_root = self.working_dir.parent == self.working_dir
        self.btn_up.setEnabled(enabled and not is_root)
        self.btn_cancel.setEnabled(not enabled)

    def populate_file_list(self) -> None:
        """Populate the tree widget with files and directories."""
        self.file_tree_widget.clear()
        self.populate_directory(self.working_dir, None)

    def add_dir_node(self, parent_item: QtWidgets.QTreeWidgetItem | None, path: Path) -> QtWidgets.QTreeWidgetItem:
        """Adds a directory node to the tree, with a dummy child to make it expandable."""
        node = QtWidgets.QTreeWidgetItem([path.name])
        node.setFlags(node.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
        node.setCheckState(0, QtCore.Qt.CheckState.Unchecked)
        node.setData(0, self.PATH_ROLE, path)
        node.setIcon(0, self.icon_provider.icon(QtWidgets.QFileIconProvider.IconType.Folder))

        # Add a fake child to make the expander arrow show up
        node.addChild(QtWidgets.QTreeWidgetItem())

        if parent_item:
            parent_item.addChild(node)
        else:
            self.file_tree_widget.addTopLevelItem(node)
        return node

    def add_file_node(self, parent_item: QtWidgets.QTreeWidgetItem, path: Path) -> None:
        """Adds a file node to the tree."""
        try:
            qfileinfo = QtCore.QFileInfo(str(path))
            specific_icon = self.icon_provider.icon(qfileinfo)
        except Exception:
            specific_icon = QtGui.QIcon()

        item_icon = specific_icon if not specific_icon.isNull() else self.icon_provider.icon(QtWidgets.QFileIconProvider.IconType.File)
        item = QtWidgets.QTreeWidgetItem([path.name])
        item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, QtCore.Qt.CheckState.Unchecked)
        item.setData(0, self.PATH_ROLE, path)
        item.setIcon(0, item_icon)
        parent_item.addChild(item)

    @QtCore.pyqtSlot(QtWidgets.QTreeWidgetItem)
    def populate_children(self, item: QtWidgets.QTreeWidgetItem):
        """Populates the children of a directory item when it's expanded."""
        # Check if it's the first expansion (dummy child is present)
        if not (item.childCount() > 0 and item.child(0).data(0, self.PATH_ROLE) is None):
            return # Already populated

        item.takeChildren() # Remove the dummy child

        path: Path | None = item.data(0, self.PATH_ROLE)
        if path and path.is_dir():
            self.populate_directory(path, item)

    def populate_directory(self, directory: Path, parent_item: QtWidgets.QTreeWidgetItem | None):
        """Populate the tree widget with files and directories for one level."""
        selected_exts, selected_names, handle_other = self.get_selected_filter_sets()
        search_text = self.search_entry.text().lower().strip()

        script_path = None
        if '__file__' in globals():
            try:
                script_path = Path(__file__).resolve()
            except NameError:
                 script_path = None

        try:
            entries = []
            for entry in os.scandir(directory):
                item_path = Path(entry.path)

                # Use relative path for ignore checks if possible
                try:
                    relative_path = item_path.relative_to(self.working_dir)
                    relative_path_str_for_ignore = str(relative_path)
                except ValueError:
                    relative_path_str_for_ignore = entry.name

                if entry.is_dir(follow_symlinks=False) and not relative_path_str_for_ignore.endswith('/'):
                    relative_path_str_for_ignore += '/'

                if self.ignore_spec and self.ignore_spec.match_file(relative_path_str_for_ignore):
                    continue

                if entry.name.startswith('.'):
                    continue

                if script_path and item_path.resolve() == script_path:
                    continue

                if entry.is_symlink():
                    logging.info(f"Skipping symbolic link in listing: {entry.name}")
                    continue

                if search_text and search_text not in entry.name.lower():
                    continue

                try:
                     if not os.access(entry.path, os.R_OK): continue
                     if entry.is_dir() and not os.access(entry.path, os.X_OK): continue
                except OSError: continue

                entries.append((entry, item_path))

            entries.sort(key=lambda x: (not x[0].is_dir(), x[0].name.lower()))

            for entry, item_path in entries:
                if entry.is_dir():
                    self.add_dir_node(parent_item, item_path)
                elif entry.is_file():
                    if not (selected_exts or selected_names or handle_other) or \
                       matches_file_type(item_path, selected_exts, selected_names, self.ALL_EXTENSIONS, self.ALL_FILENAMES, handle_other):
                        self.add_file_node(parent_item, item_path)

        except PermissionError as e:
            logging.error(f"Permission denied accessing directory: {directory}. {e}")
            if parent_item: parent_item.setDisabled(True)
        except Exception as e:
            logging.error(f"Error listing directory {directory}: {e}", exc_info=True)
            if parent_item: parent_item.setDisabled(True)

    def refresh_files(self) -> None:
        """Refresh list (reload ignores)."""
        if self.is_generating: return
        self.ignore_spec = load_ignore_patterns(self.working_dir)
        self.populate_file_list()

    def handle_item_double_click(self, item: QtWidgets.QTreeWidgetItem, column: int):
        """Navigate into directory."""
        if self.is_generating: return
        path_data = item.data(0, self.PATH_ROLE)
        if path_data and isinstance(path_data, Path):
            try:
                st = path_data.lstat()
                if stat.S_ISDIR(st.st_mode):
                    _ = list(os.scandir(path_data))
                    self.working_dir = path_data.resolve()
                    logging.info(f"Navigated into directory: {self.working_dir}")
                    self.refresh_files()
                    self.search_entry.clear()
            except PermissionError:
                 logging.warning(f"Permission denied trying to navigate into {path_data}")
                 QtWidgets.QMessageBox.warning(self, "Access Denied", f"Cannot open directory:\n{path_data.name}\n\nPermission denied.")
            except FileNotFoundError:
                 logging.warning(f"Directory not found (deleted?) on double click: {path_data}")
                 QtWidgets.QMessageBox.warning(self, "Not Found", f"Directory not found:\n{path_data.name}")
                 self.refresh_files()
            except Exception as e:
                 logging.error(f"Error navigating into directory {path_data}: {e}", exc_info=True)
                 QtWidgets.QMessageBox.warning(self, "Navigation Error", f"Could not open directory:\n{path_data.name}\n\n{e}")

    def go_up_directory(self):
        """Navigate up."""
        if self.is_generating: return
        parent_dir = self.working_dir.parent
        if parent_dir != self.working_dir:
            try:
                _ = list(os.scandir(parent_dir))
                self.working_dir = parent_dir.resolve()
                logging.info(f"Navigated up to directory: {self.working_dir}")
                self.refresh_files()
                self.search_entry.clear()
            except PermissionError:
                 logging.warning(f"Permission denied trying to navigate up to {parent_dir}")
                 QtWidgets.QMessageBox.warning(self, "Access Denied", f"Cannot open parent directory:\n{parent_dir}\n\nPermission denied.")
            except FileNotFoundError:
                 logging.warning(f"Parent directory not found (deleted?): {parent_dir}")
                 QtWidgets.QMessageBox.warning(self, "Not Found", f"Parent directory not found:\n{parent_dir}")
            except Exception as e:
                 logging.error(f"Error navigating up to directory {parent_dir}: {e}", exc_info=True)
                 QtWidgets.QMessageBox.warning(self, "Navigation Error", f"Could not open parent directory:\n{parent_dir}\n\n{e}")

    def select_all(self) -> None:
        """Select all checkable items."""
        if self.is_generating: return
        self._set_all_items_checked(True)

    def deselect_all(self) -> None:
        """Deselect all checkable items."""
        if self.is_generating: return
        self._set_all_items_checked(False)

    def _set_all_items_checked(self, checked: bool):
        """Recursively set the checked state of all items."""
        check_state = QtCore.Qt.CheckState.Checked if checked else QtCore.Qt.CheckState.Unchecked
        for i in range(self.file_tree_widget.topLevelItemCount()):
            self._set_item_checked_recursive(self.file_tree_widget.topLevelItem(i), check_state)

    def _set_item_checked_recursive(self, item: QtWidgets.QTreeWidgetItem, check_state: QtCore.Qt.CheckState):
        """Recursively set the checked state of an item and its children."""
        if item.flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable:
            item.setCheckState(0, check_state)
        for i in range(item.childCount()):
            self._set_item_checked_recursive(item.child(i), check_state)

    def _collect_selected_paths(self, item: QtWidgets.QTreeWidgetItem) -> list[Path]:
        """Recursively collect all checked file paths from the tree."""
        paths = []
        item_path = item.data(0, self.PATH_ROLE)
        if item_path and isinstance(item_path, Path):
            if item.checkState(0) == QtCore.Qt.CheckState.Checked:
                # If the item is checked, add its path and don't recurse into children.
                # This allows users to select an entire directory by checking it.
                paths.append(item_path)
            else:
                # If the item is unchecked, check its children.
                # This allows users to select individual files within a directory.
                for i in range(item.childCount()):
                    child = item.child(i)
                    paths.extend(self._collect_selected_paths(child))
        return paths

    def start_generate_file(self) -> None:
        """Initiates the file generation process in a background thread."""
        if self.is_generating:
            logging.warning("Generation process already running.")
            return

        selected_exts, selected_names, handle_other = self.get_selected_filter_sets()
        if not selected_exts and not selected_names and not handle_other:
            QtWidgets.QMessageBox.warning(self, "No File Types", "Please select at least one file type.")
            return

        selected_paths = self._collect_selected_paths_recursive()

        if not selected_paths:
            QtWidgets.QMessageBox.warning(self, "No Selection", "Please select at least one file or directory.")
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
            selected_exts=selected_exts,
            selected_names=selected_names,
            all_exts=self.ALL_EXTENSIONS,
            all_names=self.ALL_FILENAMES,
            handle_other=handle_other,
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

    def _collect_selected_paths_recursive(self) -> list[Path]:
        """Collect all selected paths from the tree widget."""
        paths = []
        for i in range(self.file_tree_widget.topLevelItemCount()):
            item = self.file_tree_widget.topLevelItem(i)
            paths.extend(self._collect_selected_paths(item))
        return paths

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
    QtCore.QCoreApplication.setApplicationVersion("1.5-tree")

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