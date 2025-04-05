import sys
import os
import logging
from pathlib import Path
from datetime import datetime
import pathspec
import stat
import traceback # For detailed error logging in worker

# PyQt6 imports
from PyQt6 import QtCore, QtWidgets, QtGui

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# --- Helper Function for Ignore Patterns ---
# (load_ignore_patterns remains the same)
def load_ignore_patterns(directory: Path) -> pathspec.PathSpec | None:
    """Loads ignore patterns from .gitignore in the specified directory."""
    gitignore_path = directory / ".gitignore"
    patterns = []
    # Add some common default ignores (optional, adjust as needed)
    # patterns.extend(['.git', '__pycache__', 'node_modules', '*.log', '*.tmp', 'venv', '.venv'])
    if gitignore_path.is_file():
        try:
            with gitignore_path.open("r", encoding="utf-8", errors='ignore') as f: # Ignore errors reading gitignore
                patterns.extend(f.readlines())
            # logging.debug(f"Loaded ignore patterns from: {gitignore_path}") # Debug level
        except Exception as e:
            logging.warning(f"Could not read {gitignore_path}: {e}")

    if patterns:
        try:
             # Pathspec works relative to the directory containing the ignore file
            return pathspec.PathSpec.from_lines(pathspec.patterns.GitWildMatchPattern, patterns)
        except Exception as e:
            logging.error(f"Error parsing ignore patterns from {gitignore_path}: {e}")
            return None # Return None if parsing fails
    return None
# ------------------------------------------

# --- Worker Class for Background Processing ---
class GeneratorWorker(QtCore.QObject):
    """
    Worker object to perform file counting and concatenation in a separate thread.
    """
    # Signals to communicate with the main thread
    pre_count_finished = QtCore.pyqtSignal(int) # Emits total files count
    progress_updated = QtCore.pyqtSignal(int)   # Emits current progress percentage
    status_updated = QtCore.pyqtSignal(str)     # Emits status messages (e.g., "Processing file X")
    finished = QtCore.pyqtSignal(str, str)      # Emits (result_content, error_message) on completion

    def __init__(self, selected_paths: list[Path], base_dir: Path, language: str, lang_exts: list[str], base_ignore_spec: pathspec.PathSpec | None, script_path: Path | None):
        super().__init__()
        self.selected_paths = selected_paths
        self.base_dir = base_dir
        self.current_language = language
        self.allowed_extensions = lang_exts
        self.base_ignore_spec = base_ignore_spec # Ignore spec relative to base_dir
        self.script_path = script_path # To avoid processing self
        self._is_cancelled = False # Flag to allow cancelling the worker

    def cancel(self):
        """Signals the worker to stop processing."""
        self._is_cancelled = True
        logging.info("Cancellation requested for worker.")

    def is_binary(self, filepath: Path) -> bool:
        """Check if a file is likely binary by looking for null bytes."""
        # (Same implementation as before)
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

    def get_file_content(self, filepath: Path) -> str | None:
        """
        Safely read the content of a non-binary text file using UTF-8 encoding.
        Returns None if the file is binary, cannot be read, or causes decoding errors.
        """
        # (Same implementation as before, using self.is_binary)
        if self.is_binary(filepath):
            logging.warning(f"Skipping binary file detected during read: {filepath.name}")
            return None
        try:
            content = filepath.read_text(encoding='utf-8', errors='strict')
            if not content:
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
            if self._is_cancelled: return count # Check cancellation periodically
            root_path = Path(root)
            try:
                 root_relative_to_base = root_path.relative_to(self.base_dir)
                 root_relative_to_current = root_path.relative_to(dir_path)
            except ValueError:
                 logging.warning(f"Count: Could not make path relative during walk: {root_path}. Skipping subtree.")
                 dirs[:] = []
                 continue

            # Filter dirs based on combined ignore rules
            original_dirs = list(dirs)
            dirs[:] = [d for d in original_dirs if not d.startswith('.') and
                       (not self.base_ignore_spec or not self.base_ignore_spec.match_file(str(root_relative_to_base / d) + '/')) and
                       (not current_dir_ignore_spec or not current_dir_ignore_spec.match_file(str(root_relative_to_current / d) + '/'))
                      ]

            for file_name in files:
                if self._is_cancelled: return count
                if file_name.startswith('.'): continue

                count_path = root_path / file_name

                try: # Check lstat type first
                    st = count_path.lstat()
                    if not stat.S_ISREG(st.st_mode): continue # Skip non-regular files/links found in walk
                except OSError: continue # Skip if stat fails

                try:
                    rel_base = count_path.relative_to(self.base_dir)
                    rel_dir = count_path.relative_to(dir_path)
                except ValueError: continue

                # Combined ignore check for files
                if (self.base_ignore_spec and self.base_ignore_spec.match_file(str(rel_base))) or \
                   (current_dir_ignore_spec and current_dir_ignore_spec.match_file(str(rel_dir))):
                    continue

                # Avoid counting self
                if self.script_path and count_path.resolve() == self.script_path:
                    continue

                # Check language and binary status
                if self.current_language == "All Files" or count_path.suffix.lower() in self.allowed_extensions:
                    if not self.is_binary(count_path): # Check binary status here
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

            # Filter dirs based on combined ignore rules (same logic as count)
            original_dirs = list(dirs)
            dirs[:] = [d for d in original_dirs if not d.startswith('.') and
                       (not self.base_ignore_spec or not self.base_ignore_spec.match_file(str(root_relative_to_base / d) + '/')) and
                       (not current_dir_ignore_spec or not current_dir_ignore_spec.match_file(str(root_relative_to_current / d) + '/'))
                      ]

            for file_name in files:
                if self._is_cancelled: return
                if file_name.startswith('.'): continue

                full_path = root_path / file_name

                try: # Check lstat type
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

                # Combined ignore check for the file
                if (self.base_ignore_spec and self.base_ignore_spec.match_file(str(relative_path_to_base))) or \
                   (current_dir_ignore_spec and current_dir_ignore_spec.match_file(str(relative_path_to_current))):
                    continue

                # Avoid processing self
                if self.script_path and full_path.resolve() == self.script_path:
                    continue

                # Language filter
                if self.current_language != "All Files":
                    if full_path.suffix.lower() not in self.allowed_extensions:
                        continue

                # Get content (includes binary check, empty check, read errors)
                file_content = self.get_file_content(full_path)
                if file_content is None: # None indicates skip
                    continue

                # Append to output
                relative_path_output = relative_path_to_base # Use path relative to overall base dir
                ext = full_path.suffix[1:] if full_path.suffix else 'txt'
                output_content.append(f"\n--- File: {relative_path_output} ---")
                output_content.append(f"```{ext}")
                output_content.append(file_content)
                output_content.append("```\n")

                # Increment counter (passed as list to be mutable)
                files_processed_counter[0] += 1
                # Don't emit progress here directly, let the main run loop do it


    @QtCore.pyqtSlot()
    def run(self):
        """Main execution method for the worker thread."""
        total_files = 0
        output_content = []
        error_message = ""
        processed_files_count = [0] # Use list for mutable counter reference
        current_progress = 0

        try:
            # --- Phase 1: Counting Files ---
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
                    except ValueError: pass # Okay if not relative

                    if is_regular_file:
                         # Check base ignore spec
                        if self.base_ignore_spec and self.base_ignore_spec.match_file(rel_path_str):
                            continue
                        # Avoid counting self
                        if self.script_path and path.resolve() == self.script_path:
                            continue
                        # Check language and binary
                        if not path.name.startswith('.') and not self.is_binary(path):
                            if self.current_language == "All Files" or path.suffix.lower() in self.allowed_extensions:
                                total_files += 1
                    elif is_regular_dir:
                        # Check if dir itself is ignored by base spec
                        if self.base_ignore_spec and self.base_ignore_spec.match_file(rel_path_str + '/'):
                            continue
                        # Load ignore spec for this specific directory
                        current_dir_ignore_spec = load_ignore_patterns(path)
                        total_files += self.count_files_recursive(path, current_dir_ignore_spec)

                except (OSError, ValueError) as e:
                    logging.warning(f"Cannot access or process {path} during pre-count: {e}")
                    continue # Skip this item for counting

            if self._is_cancelled:
                logging.info("Worker cancelled during counting phase.")
                self.finished.emit("", "Operation cancelled.")
                return

            logging.info(f"Worker: Counted {total_files} potential files.")
            self.pre_count_finished.emit(total_files) # Signal main thread count is done

            if total_files == 0:
                 logging.info("Worker: No files to process.")
                 self.finished.emit("", "") # No error, just no content
                 return

            # --- Phase 2: Processing Files ---
            logging.info("Worker: Starting file processing...")
            self.status_updated.emit("Processing...")

            # Use max(1, total_files) to avoid division by zero if count somehow ends up 0
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
                    except ValueError: pass # Okay if not relative

                    if is_regular_file:
                        # Check base ignore spec again
                        if self.base_ignore_spec and self.base_ignore_spec.match_file(rel_path_base_str):
                            continue
                        # Avoid processing self
                        if self.script_path and path.resolve() == self.script_path:
                            continue
                        # Language filter
                        if self.current_language != "All Files" and path.suffix.lower() not in self.allowed_extensions:
                             continue

                        file_content = self.get_file_content(path)
                        if file_content is not None:
                            ext = path.suffix[1:] if path.suffix else 'txt'
                            output_content.append(f"\n--- File: {rel_path_base_str} ---")
                            output_content.append(f"```{ext}")
                            output_content.append(file_content)
                            output_content.append("```\n")
                            processed_files_count[0] += 1

                            # Emit progress
                            new_progress = int((processed_files_count[0] / total_files_for_progress) * 100)
                            if new_progress > current_progress:
                                current_progress = new_progress
                                self.progress_updated.emit(current_progress)


                    elif is_regular_dir:
                        # Check if dir ignored by base spec
                        if self.base_ignore_spec and self.base_ignore_spec.match_file(rel_path_base_str + '/'):
                            continue
                        # Load specific ignore spec and process recursively
                        current_dir_ignore_spec = load_ignore_patterns(path)
                        start_count = processed_files_count[0]
                        self.process_directory_recursive(path, current_dir_ignore_spec, output_content, processed_files_count)
                        end_count = processed_files_count[0]

                        # Emit progress after directory processing
                        if end_count > start_count:
                            new_progress = int((end_count / total_files_for_progress) * 100)
                            if new_progress > current_progress:
                                current_progress = new_progress
                                self.progress_updated.emit(current_progress)


                    # Add a small yield point (optional, can help responsiveness if processing many small items quickly)
                    # QtCore.QThread.msleep(1)

                except (OSError, ValueError) as e:
                     logging.error(f"Worker: Error processing item {path.name}: {e}")
                     # Optionally append to an error summary?
                     continue # Continue with next item
                except Exception as e:
                    logging.error(f"Worker: Unexpected error processing item {path.name}: {e}", exc_info=True)
                    error_message = f"Unexpected error during processing: {e}"
                    # Optionally break here or collect errors? For now, continue.
                    continue

            if self._is_cancelled:
                logging.info("Worker cancelled during processing phase.")
                self.finished.emit("", "Operation cancelled.")
                return

            # Ensure progress reaches 100 if finished successfully
            if not error_message:
                 self.progress_updated.emit(100)

            logging.info("Worker finished processing.")
            final_content = '\n'.join(output_content)
            self.finished.emit(final_content, error_message if error_message else "")

        except Exception as e:
            # Catchall for unexpected errors in the run method itself
            logging.error(f"Critical error in worker run method: {e}", exc_info=True)
            detailed_error = traceback.format_exc()
            self.finished.emit("", f"Critical worker error: {e}\n{detailed_error}")

# --- Main Application Window ---
class FileConcatenator(QtWidgets.QMainWindow):
    """
    A PyQt6-based graphical application... (docstring remains similar)
    """
    PATH_ROLE = QtCore.Qt.ItemDataRole.UserRole + 1

    def __init__(self, working_dir: Path = None) -> None:
        super().__init__()
        self.initial_base_dir = (working_dir or Path.cwd()).resolve()
        self.working_dir = self.initial_base_dir
        self.setWindowTitle(f"SOTA Concatenator - [{self.working_dir.name}]")
        self.resize(700, 550)

        self.ignore_spec = load_ignore_patterns(self.working_dir)
        self.icon_provider = QtWidgets.QFileIconProvider()

        # --- Store worker and thread references ---
        self.worker_thread = None
        self.worker = None
        self.is_generating = False # Flag to prevent multiple generations
        # ------------------------------------------

        # (language_extensions remains the same)
        self.language_extensions = {
            "All Files": ["*"], "Python": [".py", ".pyw", ".pyx"], "JavaScript": [".js", ".jsx", ".ts", ".tsx"],
            "Java": [".java"], "C/C++": [".c", ".cpp", ".h", ".hpp"], "Ruby": [".rb", ".rake"],
            "PHP": [".php"], "Go": [".go"], "Rust": [".rs"], "Swift": [".swift"], "HTML/CSS": [".html", ".htm", ".css"],
            "Markdown": [".md", ".markdown"], "Text": [".txt"], "JSON/YAML": [".json", ".yaml", ".yml"],
            "XML": [".xml"], "Shell": [".sh", ".bash", ".zsh"],
        }


        self.init_ui()
        self.populate_file_list()

    def init_ui(self) -> None:
        """Create and place all PyQt6 widgets."""
        central_widget = QtWidgets.QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QtWidgets.QVBoxLayout(central_widget)

        # --- Top Layout (remains mostly the same) ---
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

        language_label = QtWidgets.QLabel("Language Filter:")
        top_nav_layout.addWidget(language_label)
        self.language_dropdown = QtWidgets.QComboBox()
        self.language_dropdown.addItems(list(self.language_extensions.keys()))
        self.language_dropdown.setCurrentText("All Files")
        top_nav_layout.addWidget(self.language_dropdown)
        self.language_dropdown.currentTextChanged.connect(self.refresh_files)

        search_label = QtWidgets.QLabel("Search:")
        top_nav_layout.addWidget(search_label)
        self.search_entry = QtWidgets.QLineEdit()
        self.search_entry.setPlaceholderText("Filter items...")
        top_nav_layout.addWidget(self.search_entry)
        self.search_entry.textChanged.connect(self.refresh_files)
        top_nav_layout.addStretch()
        main_layout.addLayout(top_nav_layout)
        # --- End Top Layout ---

        # --- File List Widget (remains the same) ---
        self.file_list_widget = QtWidgets.QListWidget()
        self.file_list_widget.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_list_widget.itemDoubleClicked.connect(self.handle_item_double_click)
        self.file_list_widget.setAlternatingRowColors(True)
        main_layout.addWidget(self.file_list_widget)
        # --- ------------------------------------ ---

        # --- Bottom Layout (remains mostly the same) ---
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
        # Max will be set dynamically after pre-count
        self.progress_bar.setMaximum(100) # Default max
        self.progress_bar.setValue(0)
        self.progress_bar.setMinimumWidth(200)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%") # Default format
        bottom_layout.addWidget(self.progress_bar)

        # Add a Cancel button
        self.btn_cancel = QtWidgets.QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.cancel_generation)
        self.btn_cancel.setEnabled(False) # Initially disabled
        bottom_layout.addWidget(self.btn_cancel)


        self.btn_generate = QtWidgets.QPushButton("Generate File")
        self.btn_generate.clicked.connect(self.start_generate_file) # Connect to start method
        bottom_layout.addWidget(self.btn_generate)
        main_layout.addLayout(bottom_layout)
        # --- End Bottom Layout ---

        self.update_ui_state()

    # --- UI Update and State Management ---
    def update_ui_state(self) -> None:
        """Updates UI elements based on the current state."""
        # (Same implementation as before)
        try:
            display_path = self.working_dir.relative_to(self.initial_base_dir)
            title_path = f".../{display_path}" if display_path != Path('.') else self.initial_base_dir.name
        except ValueError:
            title_path = str(self.working_dir)
        self.setWindowTitle(f"SOTA Concatenator - [{title_path}]")
        self.current_path_label.setText(str(self.working_dir))
        self.current_path_label.setCursorPosition(0)
        is_root = self.working_dir.parent == self.working_dir
        self.btn_up.setEnabled(not is_root and not self.is_generating) # Also disable if generating

    def set_controls_enabled(self, enabled: bool):
        """Enable/disable controls during generation."""
        self.btn_generate.setEnabled(enabled)
        self.btn_select_all.setEnabled(enabled)
        self.btn_deselect_all.setEnabled(enabled)
        self.file_list_widget.setEnabled(enabled)
        self.language_dropdown.setEnabled(enabled)
        self.search_entry.setEnabled(enabled)
        # Only enable Up button if not at root AND not generating
        is_root = self.working_dir.parent == self.working_dir
        self.btn_up.setEnabled(enabled and not is_root)
        # Cancel button is enabled ONLY when generating
        self.btn_cancel.setEnabled(not enabled)

    # --- File/Directory Handling (Minor changes maybe needed for self path) ---
    # is_binary can be removed here if only used by worker, or kept for populate_file_list
    def is_binary(self, filepath: Path) -> bool:
        """Check if a file is likely binary by looking for null bytes."""
        CHUNK_SIZE = 1024
        try:
            with filepath.open('rb') as f:
                chunk = f.read(CHUNK_SIZE)
            return b'\0' in chunk
        except OSError as e:
            logging.warning(f"Could not read start of file {filepath} to check if binary: {e}")
            return True # Treat as binary if we can't even read the start
        except Exception as e:
            logging.error(f"Unexpected error checking if file is binary {filepath}: {e}", exc_info=True)
            return True # Treat as binary on unexpected errors

    def populate_file_list(self) -> None:
        """Populate the list widget (mostly same, ensure self-skip works)."""
        # (Same implementation as before, but ensure script_name logic is robust)
        self.file_list_widget.clear()
        selected_language = self.language_dropdown.currentText()
        allowed_extensions = self.language_extensions.get(selected_language, ["*"])
        search_text = self.search_entry.text().lower().strip()
        directories = []
        files = []

        # Get the absolute path of the script file
        script_path = None
        if '__file__' in globals():
            try:
                script_path = Path(__file__).resolve()
            except NameError: # Handle cases like running interactively where __file__ is not defined
                 script_path = None
                 logging.warning("__file__ not defined, cannot reliably skip script file.")


        try:
            for entry in os.scandir(self.working_dir):
                item_path = Path(entry.path)
                relative_path_str_for_ignore = entry.name
                if entry.is_dir(follow_symlinks=False) and not relative_path_str_for_ignore.endswith('/'):
                    relative_path_str_for_ignore += '/'

                if self.ignore_spec and self.ignore_spec.match_file(relative_path_str_for_ignore):
                    continue

                # Skip hidden and self (compare resolved paths)
                if entry.name.startswith('.') or (script_path and item_path.resolve() == script_path):
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

                if entry.is_dir():
                    directories.append(item_path)
                elif entry.is_file():
                    if self.is_binary(item_path): continue # Use self.is_binary here
                    if selected_language != "All Files":
                        if item_path.suffix.lower() not in allowed_extensions: continue
                    files.append(item_path)

        except PermissionError as e:
            logging.error(f"Permission denied accessing directory: {self.working_dir}. {e}")
            QtWidgets.QMessageBox.critical(self, "Access Denied", f"Could not read directory contents:\n{self.working_dir}\n\n{e}")
            return
        except Exception as e:
            logging.error(f"Error listing directory {self.working_dir}: {e}", exc_info=True)
            QtWidgets.QMessageBox.warning(self, "Listing Error", f"An error occurred while listing directory contents:\n{e}")

        directories.sort(key=lambda p: p.name.lower())
        files.sort(key=lambda p: p.name.lower())

        self.file_list_widget.clear()
        dir_icon = self.icon_provider.icon(QtWidgets.QFileIconProvider.IconType.Folder)
        for directory in directories:
            item = QtWidgets.QListWidgetItem(dir_icon, directory.name)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.CheckState.Unchecked)
            item.setData(self.PATH_ROLE, directory)
            self.file_list_widget.addItem(item)

        file_icon = self.icon_provider.icon(QtWidgets.QFileIconProvider.IconType.File)
        for file_item in files:
            try:
                qfileinfo = QtCore.QFileInfo(str(file_item))
                specific_icon = self.icon_provider.icon(qfileinfo)
            except Exception: specific_icon = QtGui.QIcon()
            item_icon = specific_icon if not specific_icon.isNull() else file_icon
            item = QtWidgets.QListWidgetItem(item_icon, file_item.name)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.CheckState.Unchecked)
            item.setData(self.PATH_ROLE, file_item)
            self.file_list_widget.addItem(item)

        self.update_ui_state()


    def refresh_files(self) -> None:
        """Refresh list (reload ignores)."""
        if self.is_generating: return # Don't refresh while generating
        self.ignore_spec = load_ignore_patterns(self.working_dir)
        self.populate_file_list()

    def handle_item_double_click(self, item: QtWidgets.QListWidgetItem):
        """Navigate into directory."""
        if self.is_generating: return # Don't navigate while generating
        # (Same implementation as before)
        path_data = item.data(self.PATH_ROLE)
        if path_data and isinstance(path_data, Path):
            try:
                st = path_data.lstat()
                if stat.S_ISDIR(st.st_mode):
                    _ = list(os.scandir(path_data))
                    self.working_dir = path_data.resolve()
                    logging.info(f"Navigated into directory: {self.working_dir}")
                    self.refresh_files()
                    self.search_entry.clear()
                elif stat.S_ISREG(st.st_mode):
                     logging.debug(f"Double click on file item: {item.text()}")
                elif stat.S_ISLNK(st.st_mode):
                     logging.debug(f"Double click on symlink item: {item.text()}")
                else:
                     logging.debug(f"Double click on non-dir/file/link item: {item.text()}")
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
        else:
             logging.debug(f"Double click on item with no path data: {item.text()}")


    def go_up_directory(self):
        """Navigate up."""
        if self.is_generating: return # Don't navigate while generating
        # (Same implementation as before)
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
        else:
            logging.debug("Already at the root directory, cannot go up further.")

    # --- Selection ---
    def select_all(self) -> None:
        """Select all checkable items."""
        if self.is_generating: return
        # (Same implementation as before)
        for i in range(self.file_list_widget.count()):
            item = self.file_list_widget.item(i)
            if item.flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable:
                 item.setCheckState(QtCore.Qt.CheckState.Checked)


    def deselect_all(self) -> None:
        """Deselect all checkable items."""
        if self.is_generating: return
        # (Same implementation as before)
        for i in range(self.file_list_widget.count()):
            item = self.file_list_widget.item(i)
            if item.flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable:
                 item.setCheckState(QtCore.Qt.CheckState.Unchecked)

    # --- Generation Logic (using QThread) ---

    def start_generate_file(self) -> None:
        """Initiates the file generation process in a background thread."""
        if self.is_generating:
            logging.warning("Generation process already running.")
            return

        selected_paths = []
        for i in range(self.file_list_widget.count()):
            item = self.file_list_widget.item(i)
            if item.flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable and \
               item.checkState() == QtCore.Qt.CheckState.Checked:
                path_data = item.data(self.PATH_ROLE)
                if path_data and isinstance(path_data, Path):
                    selected_paths.append(path_data)

        if not selected_paths:
            QtWidgets.QMessageBox.warning(self, "No Selection", "Please select at least one file or directory.")
            return

        self.is_generating = True
        self.set_controls_enabled(False) # Disable UI
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(100) # Reset max until count is known
        self.progress_bar.setFormat("Starting...")

        # Get script path to pass to worker
        script_path = Path(__file__).resolve() if '__file__' in globals() else None

        # Create worker and thread
        self.worker_thread = QtCore.QThread()
        self.worker = GeneratorWorker(
            selected_paths=selected_paths,
            base_dir=self.working_dir,
            language=self.language_dropdown.currentText(),
            lang_exts=self.language_extensions[self.language_dropdown.currentText()],
            base_ignore_spec=self.ignore_spec, # Pass the spec loaded for the current view
            script_path=script_path
        )
        self.worker.moveToThread(self.worker_thread)

        # Connect signals and slots
        # Worker -> GUI updates
        self.worker.pre_count_finished.connect(self.handle_pre_count)
        self.worker.progress_updated.connect(self.handle_progress_update)
        self.worker.status_updated.connect(self.handle_status_update)
        self.worker.finished.connect(self.handle_generation_finished)
        # Thread control
        self.worker_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.worker_thread.quit)
        # Cleanup
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.finished.connect(self.generation_cleanup) # Additional cleanup slot


        logging.info("Starting generator thread...")
        self.worker_thread.start()


    @QtCore.pyqtSlot(int)
    def handle_pre_count(self, total_files: int):
        """Slot to handle the pre_count_finished signal."""
        logging.info(f"Received pre-count: {total_files}")
        # Set max to total_files for accurate progress, or 100 if 0 files
        # self.progress_bar.setMaximum(max(1, total_files)) # If tracking files directly
        self.progress_bar.setMaximum(100) # Keep percentage based
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%") # Use standard percentage format


    @QtCore.pyqtSlot(int)
    def handle_progress_update(self, value: int):
        """Slot to handle the progress_updated signal."""
        self.progress_bar.setValue(value)

    @QtCore.pyqtSlot(str)
    def handle_status_update(self, message: str):
        """Slot to handle the status_updated signal."""
        # Update progress bar text or a dedicated status label if you add one
        self.progress_bar.setFormat(message + " %p%")


    @QtCore.pyqtSlot(str, str)
    def handle_generation_finished(self, result_content: str, error_message: str):
        """Slot to handle the finished signal from the worker."""
        logging.info(f"Generator worker finished. Error: '{error_message}'")

        # Ensure progress bar shows 100% unless cancelled or errored significantly
        if not error_message:
            self.progress_bar.setValue(100)
            self.progress_bar.setFormat("Finalizing...")
        elif "cancel" in error_message.lower():
             self.progress_bar.setFormat("Cancelled")
        else:
             self.progress_bar.setFormat("Error")


        if error_message:
            if "cancel" not in error_message.lower(): # Don't show msgbox for cancellation
                 QtWidgets.QMessageBox.warning(self, "Generation Error", f"An error occurred:\n{error_message}")
            # Cleanup happens via thread.finished signal connection

        elif not result_content:
            QtWidgets.QMessageBox.information(self, "Finished", "No processable content found in the selected items matching the filters.")
            # Cleanup happens via thread.finished signal connection

        else:
            # Proceed with saving the file (this is quick, okay in main thread)
            self.save_generated_file(result_content)
            # Cleanup happens via thread.finished signal connection


    def generation_cleanup(self):
        """Slot called when the thread finishes, regardless of reason."""
        logging.info("Generator thread finished signal received. Cleaning up.")
        self.worker = None
        self.worker_thread = None
        self.is_generating = False
        self.set_controls_enabled(True) # Re-enable UI
        # Reset progress bar fully only after cleanup
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")


    def cancel_generation(self):
        """Requests cancellation of the running worker."""
        if self.worker:
            logging.info("Cancel button clicked. Requesting worker cancellation.")
            self.worker.cancel()
            self.btn_cancel.setEnabled(False) # Disable cancel button after clicking
            self.progress_bar.setFormat("Cancelling...")
        else:
            logging.warning("Cancel clicked but no worker active.")


    def save_generated_file(self, content: str):
        """Handles the save file dialog and writing the output."""
        desktop_path = Path.home() / "Desktop"
        if not desktop_path.exists(): desktop_path = Path.home()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        initial_filename = f"concatenated_{self.working_dir.name}_{timestamp}.md"
        default_path = str(desktop_path / initial_filename)

        options = QtWidgets.QFileDialog.Option.DontUseNativeDialog
        file_tuple = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Concatenated File", default_path, "Markdown Files (*.md);;All Files (*)",
            # options=options
        )
        output_filename = file_tuple[0]

        if not output_filename:
            logging.info("Save operation cancelled by user.")
            # No result content was generated if save cancelled here
            QtWidgets.QMessageBox.information(self, "Cancelled", "Save operation cancelled.")
            # Cleanup will still run via the finished signal chain
            return

        try:
            output_path = Path(output_filename)
            if '__file__' in globals() and output_path.resolve() == Path(__file__).resolve():
                 QtWidgets.QMessageBox.critical(self,"Error","Cannot overwrite the running script file!")
                 # Cleanup will still run
                 return

            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(f"# Concatenated Files from: {self.working_dir}\n")
                f.write(f"# Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"# Selected language filter: {self.language_dropdown.currentText()}\n")
                f.write("--- START OF CONTENT ---\n")
                f.write(content) # Content already includes newlines between files
                f.write("\n--- END OF CONTENT ---\n")
            QtWidgets.QMessageBox.information(self, "Success", f"File generated successfully:\n{output_filename}")
            logging.info(f"Successfully generated file: {output_filename}")
        except Exception as e:
            logging.error(f"Error writing output file {output_filename}: {e}", exc_info=True)
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Could not write output file:\n{output_filename}\n\n{e}"
            )
        finally:
             # Explicitly reset progress bar appearance here after save attempt
             # although generation_cleanup should also handle it.
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
                # Wait briefly for thread to potentially finish after cancel request?
                # Or just accept the event and let OS handle thread termination?
                # For simplicity, accept and let OS handle it. Resources should be released.
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


# --- Main block ---
if __name__ == "__main__":
    QtCore.QCoreApplication.setApplicationName("SOTA Concatenator")
    QtCore.QCoreApplication.setOrganizationName("YourOrg")
    QtCore.QCoreApplication.setApplicationVersion("1.2-threaded") # Version bump

    app = QtWidgets.QApplication(sys.argv)

    settings = QtCore.QSettings("YourOrg", "SOTAConcatenator")
    last_dir = settings.value("last_directory", str(Path.cwd()))

    # Use a non-modal dialog initially so the main window can appear behind it
    # then raise the dialog if needed. A bit complex, let's stick to the simple modal way:
    selected_dir = QtWidgets.QFileDialog.getExistingDirectory(
        None, "Select Project Directory To Concatenate", last_dir
    )

    if selected_dir:
        working_dir = Path(selected_dir)
        settings.setValue("last_directory", selected_dir)
    else:
        # Exit if no directory selected on startup
        logging.warning("No directory selected on startup. Exiting.")
        sys.exit(0) # Exit cleanly if user cancels initial dialog
        # Alternatively, use last_dir:
        # working_dir = Path(last_dir)
        # logging.info(f"No directory selected, using last/default: {working_dir}")


    window = FileConcatenator(working_dir=working_dir)
    window.show()
    sys.exit(app.exec())