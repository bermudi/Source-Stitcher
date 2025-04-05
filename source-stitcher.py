import sys
import os
import logging
from pathlib import Path
from datetime import datetime
import pathspec
import stat  # <--- Required for lstat checks

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
    # Add some common default ignores (optional, adjust as needed)
    # patterns.extend(['.git', '__pycache__', 'node_modules', '*.log', '*.tmp', 'venv', '.venv'])
    if gitignore_path.is_file():
        try:
            with gitignore_path.open("r", encoding="utf-8", errors='ignore') as f: # Ignore errors reading gitignore
                patterns.extend(f.readlines())
            logging.info(f"Loaded ignore patterns from: {gitignore_path}")
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

class FileConcatenator(QtWidgets.QMainWindow):
    """
    A PyQt6-based graphical application to select and concatenate multiple files
    into a single markdown file. Includes directory navigation, language-based
    filtering, search, .gitignore handling, binary file detection, and robust error handling.
    """
    # --- Class constant for UserRole data ---
    PATH_ROLE = QtCore.Qt.ItemDataRole.UserRole + 1

    def __init__(self, working_dir: Path = None) -> None:
        super().__init__()
        # --- Store the initial base directory ---
        self.initial_base_dir = (working_dir or Path.cwd()).resolve()
        self.working_dir = self.initial_base_dir
        # --------------------------------------
        self.setWindowTitle(f"SOTA Concatenator - [{self.working_dir.name}]")
        self.resize(700, 550) # Slightly taller for Up button

        self.ignore_spec = load_ignore_patterns(self.working_dir)
        self.icon_provider = QtWidgets.QFileIconProvider() # For file/dir icons

        self.language_extensions = {
            "All Files": ["*"],
            "Python": [".py", ".pyw", ".pyx"],
            "JavaScript": [".js", ".jsx", ".ts", ".tsx"],
            "Java": [".java"], # Removed binary .class/.jar
            "C/C++": [".c", ".cpp", ".h", ".hpp"],
            "Ruby": [".rb", ".rake"],
            "PHP": [".php"],
            "Go": [".go"],
            "Rust": [".rs"],
            "Swift": [".swift"],
            "HTML/CSS": [".html", ".htm", ".css"],
            "Markdown": [".md", ".markdown"],
            "Text": [".txt"],
            "JSON/YAML": [".json", ".yaml", ".yml"],
            "XML": [".xml"],
            "Shell": [".sh", ".bash", ".zsh"],
        }

        self.progress_value = 0.0

        self.init_ui()
        self.populate_file_list() # Changed method name

    def init_ui(self) -> None:
        """Create and place all PyQt6 widgets."""
        central_widget = QtWidgets.QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QtWidgets.QVBoxLayout(central_widget)

        # --- Top Navigation/Filter/Search Layout ---
        top_nav_layout = QtWidgets.QHBoxLayout()

        # --- Up Button ---
        self.btn_up = QtWidgets.QPushButton()
        self.btn_up.setIcon(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ArrowUp)) # Use standard icon
        self.btn_up.setToolTip("Go to Parent Directory (Alt+Up)")
        self.btn_up.setShortcut(QtGui.QKeySequence(QtCore.Qt.KeyboardModifier.AltModifier | QtCore.Qt.Key.Key_Up)) # Keyboard shortcut
        self.btn_up.clicked.connect(self.go_up_directory)
        self.btn_up.setFixedWidth(self.btn_up.fontMetrics().horizontalAdvance(" Up ") * 2) # Adjust width
        top_nav_layout.addWidget(self.btn_up)
        #------------------

        # --- Current Path Label ---
        self.current_path_label = QtWidgets.QLineEdit(str(self.working_dir))
        self.current_path_label.setReadOnly(True) # Make it read-only, just display
        self.current_path_label.setToolTip("Current Directory")
        top_nav_layout.addWidget(self.current_path_label)
        #-------------------------

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

        # --- Replaced ScrollArea with QListWidget ---
        self.file_list_widget = QtWidgets.QListWidget()
        self.file_list_widget.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection) # Allow multi-select if needed, though checkboxes are primary
        self.file_list_widget.itemDoubleClicked.connect(self.handle_item_double_click)
        self.file_list_widget.setAlternatingRowColors(True) # Improve readability
        main_layout.addWidget(self.file_list_widget)
        # --- ------------------------------------ ---

        # Bottom button and progress bar layout
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
        self.progress_bar.setTextVisible(True) # Show percentage
        bottom_layout.addWidget(self.progress_bar)

        self.btn_generate = QtWidgets.QPushButton("Generate File")
        self.btn_generate.clicked.connect(self.generate_file)
        bottom_layout.addWidget(self.btn_generate)

        main_layout.addLayout(bottom_layout)

        # --- Initial state update ---
        self.update_ui_state()

    def update_ui_state(self) -> None:
        """Updates UI elements based on the current state (e.g., working directory)."""
        # --- Update Window Title ---
        try:
            # Show path relative to initial base, or absolute if not inside
            display_path = self.working_dir.relative_to(self.initial_base_dir)
            title_path = f".../{display_path}" if display_path != Path('.') else self.initial_base_dir.name
        except ValueError:
            title_path = str(self.working_dir) # Show absolute if outside base
        self.setWindowTitle(f"SOTA Concatenator - [{title_path}]")
        # -------------------------

        # --- Update Path Label ---
        self.current_path_label.setText(str(self.working_dir))
        self.current_path_label.setCursorPosition(0) # Show start of path if too long
        # ------------------------

        # --- Enable/Disable Up Button ---
        is_root = self.working_dir.parent == self.working_dir
        self.btn_up.setEnabled(not is_root) # Allow going up until root
        # ------------------------------

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
        """Populate the list widget with files/dirs from the current working_dir."""
        self.file_list_widget.clear()

        selected_language = self.language_dropdown.currentText()
        allowed_extensions = self.language_extensions.get(selected_language, ["*"])
        search_text = self.search_entry.text().lower().strip()

        directories = []
        files = []
        script_name = Path(__file__).resolve().name if '__file__' in globals() else "" # Resolve __file__

        try:
            # Use scandir for potentially better performance on some systems
            for entry in os.scandir(self.working_dir):
                item_path = Path(entry.path)
                relative_path_str_for_ignore = entry.name # For ignore matching, relative to current dir

                # Check ignore rules first
                # Add '/' suffix if it's a directory for pathspec matching
                if entry.is_dir(follow_symlinks=False) and not relative_path_str_for_ignore.endswith('/'):
                    relative_path_str_for_ignore += '/'

                if self.ignore_spec and self.ignore_spec.match_file(relative_path_str_for_ignore):
                    # logging.debug(f"Ignoring '{entry.name}' due to ignore rules.")
                    continue

                # Skip hidden files/dirs and self script
                if entry.name.startswith('.') or (script_name and item_path.resolve().name == script_name):
                    continue

                # Skip symlinks explicitly in the listing phase
                if entry.is_symlink():
                    logging.info(f"Skipping symbolic link in listing: {entry.name}")
                    continue

                # Apply search filter
                if search_text and search_text not in entry.name.lower():
                    continue

                # Check permissions early - use entry attributes where possible
                try:
                     # Test read access more reliably
                     if not os.access(entry.path, os.R_OK):
                          logging.warning(f"Skipping due to lack of read permissions: {entry.name}")
                          continue
                     if entry.is_dir() and not os.access(entry.path, os.X_OK): # Need execute for dirs
                          logging.warning(f"Skipping directory due to lack of execute permissions: {entry.name}")
                          continue
                except OSError: # Handle race condition if file disappears
                    continue

                # Categorize
                if entry.is_dir():
                    directories.append(item_path)
                elif entry.is_file():
                    # Check if binary
                    if self.is_binary(item_path):
                        # logging.info(f"Skipping binary file in listing: {item_path.name}")
                        continue
                    # Apply language filter
                    if selected_language != "All Files":
                        if item_path.suffix.lower() not in allowed_extensions:
                            continue
                    files.append(item_path)

        except PermissionError as e:
            logging.error(f"Permission denied accessing directory: {self.working_dir}. {e}")
            QtWidgets.QMessageBox.critical(
                self, "Access Denied", f"Could not read directory contents:\n{self.working_dir}\n\n{e}"
            )
            # Optional: Attempt to navigate back up?
            # if self.working_dir != self.working_dir.parent:
            #     self.go_up_directory()
            return
        except Exception as e:
            logging.error(f"Error listing directory {self.working_dir}: {e}", exc_info=True)
            QtWidgets.QMessageBox.warning(
                self, "Listing Error", f"An error occurred while listing directory contents:\n{e}"
            )

        # Sort directories and files by name (case-insensitive)
        directories.sort(key=lambda p: p.name.lower())
        files.sort(key=lambda p: p.name.lower())

        # --- Populate QListWidget ---
        self.file_list_widget.clear()

        dir_icon = self.icon_provider.icon(QtWidgets.QFileIconProvider.IconType.Folder)
        # Populate Directories First
        for directory in directories:
            item = QtWidgets.QListWidgetItem(dir_icon, directory.name) # Icon and Name
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.CheckState.Unchecked)
            item.setData(self.PATH_ROLE, directory) # Store the Path object
            self.file_list_widget.addItem(item)

        # Populate Files
        file_icon = self.icon_provider.icon(QtWidgets.QFileIconProvider.IconType.File) # Generic file icon
        for file_item in files:
            # Try to get specific icon using QtCore.QFileInfo, fall back to generic
            try:
                qfileinfo = QtCore.QFileInfo(str(file_item))
                specific_icon = self.icon_provider.icon(qfileinfo)
            except Exception: # Catch potential errors with QFileInfo or icon provider
                 specific_icon = QtGui.QIcon() # Use an empty icon on error

            item_icon = specific_icon if not specific_icon.isNull() else file_icon

            item = QtWidgets.QListWidgetItem(item_icon, file_item.name) # Icon and Name
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.CheckState.Unchecked)
            item.setData(self.PATH_ROLE, file_item) # Store the Path object
            self.file_list_widget.addItem(item)
        # ---------------------------

        # --- Update UI State (Title, Up button, Path Label) ---
        self.update_ui_state()

    def refresh_files(self) -> None:
        """Refresh the list of files/dirs based on current filters and working_dir."""
        # Reload ignores relative to the potentially changed working_dir
        self.ignore_spec = load_ignore_patterns(self.working_dir)
        self.populate_file_list()

    def handle_item_double_click(self, item: QtWidgets.QListWidgetItem):
        """Navigate into the directory associated with the double-clicked item."""
        path_data = item.data(self.PATH_ROLE)
        if path_data and isinstance(path_data, Path):
            # Check if it's a directory without following symlinks using lstat
            try:
                st = path_data.lstat()
                if stat.S_ISDIR(st.st_mode):
                    # Test we can list the target directory before navigating
                    _ = list(os.scandir(path_data)) # This might raise PermissionError
                    self.working_dir = path_data.resolve() # Navigate to resolved path
                    logging.info(f"Navigated into directory: {self.working_dir}")
                    self.refresh_files()
                    self.search_entry.clear() # Clear search when navigating
                elif stat.S_ISREG(st.st_mode):
                     logging.debug(f"Double click on file item: {item.text()}")
                     # Future: Add option to open file preview or external editor
                elif stat.S_ISLNK(st.st_mode):
                     logging.debug(f"Double click on symlink item: {item.text()}")
                     # Future: Add option to navigate to symlink target? Requires careful handling.
                else:
                     logging.debug(f"Double click on non-dir/file/link item: {item.text()}")

            except PermissionError:
                 logging.warning(f"Permission denied trying to navigate into {path_data}")
                 QtWidgets.QMessageBox.warning(self, "Access Denied", f"Cannot open directory:\n{path_data.name}\n\nPermission denied.")
            except FileNotFoundError:
                 logging.warning(f"Directory not found (deleted?) on double click: {path_data}")
                 QtWidgets.QMessageBox.warning(self, "Not Found", f"Directory not found:\n{path_data.name}")
                 self.refresh_files() # Refresh list as item is gone
            except Exception as e:
                 logging.error(f"Error navigating into directory {path_data}: {e}", exc_info=True)
                 QtWidgets.QMessageBox.warning(self, "Navigation Error", f"Could not open directory:\n{path_data.name}\n\n{e}")
        else:
             logging.debug(f"Double click on item with no path data: {item.text()}")

    def go_up_directory(self):
        """Navigate to the parent directory."""
        parent_dir = self.working_dir.parent
        if parent_dir != self.working_dir: # Check if we are not already at root
            try:
                 # Test we can list the parent directory before navigating
                _ = list(os.scandir(parent_dir))
                self.working_dir = parent_dir.resolve()
                logging.info(f"Navigated up to directory: {self.working_dir}")
                self.refresh_files()
                self.search_entry.clear() # Clear search when navigating
            except PermissionError:
                 logging.warning(f"Permission denied trying to navigate up to {parent_dir}")
                 QtWidgets.QMessageBox.warning(self, "Access Denied", f"Cannot open parent directory:\n{parent_dir}\n\nPermission denied.")
            except FileNotFoundError:
                 logging.warning(f"Parent directory not found (deleted?): {parent_dir}")
                 QtWidgets.QMessageBox.warning(self, "Not Found", f"Parent directory not found:\n{parent_dir}")
                 # Maybe reset to initial_base_dir or cwd? For now, just stay put.
            except Exception as e:
                 logging.error(f"Error navigating up to directory {parent_dir}: {e}", exc_info=True)
                 QtWidgets.QMessageBox.warning(self, "Navigation Error", f"Could not open parent directory:\n{parent_dir}\n\n{e}")
        else:
            logging.debug("Already at the root directory, cannot go up further.")

    def select_all(self) -> None:
        """Select all checkable items in the list."""
        for i in range(self.file_list_widget.count()):
            item = self.file_list_widget.item(i)
            if item.flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable:
                 item.setCheckState(QtCore.Qt.CheckState.Checked)

    def deselect_all(self) -> None:
        """Deselect all checkable items in the list."""
        for i in range(self.file_list_widget.count()):
            item = self.file_list_widget.item(i)
            if item.flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable:
                 item.setCheckState(QtCore.Qt.CheckState.Unchecked)

    def get_file_content(self, filepath: Path) -> str | None:
        """
        Safely read the content of a non-binary text file using UTF-8 encoding.
        Returns None if the file is binary, cannot be read, or causes decoding errors.
        """
        # Re-check binary status before read attempt
        if self.is_binary(filepath):
            logging.warning(f"Skipping binary file detected during read: {filepath.name}")
            return None
        try:
            # Try reading with UTF-8 strict first
            content = filepath.read_text(encoding='utf-8', errors='strict')
            if not content:
                logging.info(f"Skipping empty file: {filepath.name}")
                return None # Return None to completely omit empty files
            return content
        except UnicodeDecodeError:
            # Fallback: Try reading with 'ignore' or 'replace' if strict fails?
            # Or try detecting encoding with chardet (adds dependency)?
            # For now, just log and skip on strict UTF-8 failure.
            logging.warning(f"Skipping file due to UTF-8 decoding error: {filepath.name}")
            return None
        except PermissionError:
            logging.warning(f"Skipping file due to permission error: {filepath.name}")
            return None
        except FileNotFoundError: # File might have been deleted between listing and reading
             logging.warning(f"Skipping file as it was not found (possibly deleted): {filepath.name}")
             return None
        except OSError as e: # Catch other OS errors like EIO
             logging.warning(f"Skipping file due to OS error during read: {filepath.name} ({e})")
             return None
        except Exception as e:
            # Log unexpected errors with traceback
            logging.error(f"Unexpected error reading file {filepath}: {e}", exc_info=True)
            return None

    def process_directory(self, dir_path: Path, output_content: list, progress_step: float, base_dir_for_rel_path: Path) -> None:
        """
        Recursively process a directory, respecting language filters and ignore rules.
        Appends file contents to output_content and updates the progress bar.
        Skips binary files, symlinks, and handles permissions errors during walk.
        Paths in output are relative to base_dir_for_rel_path.
        """
        selected_language = self.language_dropdown.currentText()
        allowed_extensions = self.language_extensions[selected_language]
        # Load ignore spec relative to the directory being processed
        current_dir_ignore_spec = load_ignore_patterns(dir_path)

        def walk_error_handler(error: OSError):
            # Log errors during walk (e.g., permission denied on a sub-subdir)
            logging.warning(f"Permission or other OS error during directory walk below {dir_path}: {error}")
            # Don't raise the error, just skip the problematic entry

        # Use os.walk, explicitly NOT following links, and handle errors
        for root, dirs, files in os.walk(dir_path, topdown=True, onerror=walk_error_handler, followlinks=False):
            root_path = Path(root)

            # --- Filter directories based on ignore rules (using path relative to root ignore file) ---
            try:
                 root_relative_to_base = root_path.relative_to(base_dir_for_rel_path)
                 root_relative_to_current = root_path.relative_to(dir_path)
            except ValueError:
                 logging.warning(f"Could not make path relative during walk: {root_path}. Skipping subtree.")
                 dirs[:] = [] # Don't descend further
                 continue

            # Modify dirs in-place based on combined ignore rules
            original_dirs = list(dirs) # Copy before modifying
            dirs[:] = [d for d in original_dirs if not d.startswith('.') and
                       (not self.ignore_spec or not self.ignore_spec.match_file(str(root_relative_to_base / d) + '/')) and
                       (not current_dir_ignore_spec or not current_dir_ignore_spec.match_file(str(root_relative_to_current / d) + '/'))
                      ]
            # ------------------------------------------------------------------------------------------

            for file_name in files:
                if file_name.startswith('.'):
                    continue

                full_path = root_path / file_name

                # --- Use lstat to check type within walk (avoid processing symlinks found by walk) ---
                try:
                    st = full_path.lstat()
                    if not stat.S_ISREG(st.st_mode): # Only process regular files
                        if stat.S_ISLNK(st.st_mode):
                             logging.debug(f"Skipping symlink found during walk: {full_path}")
                        else:
                             logging.debug(f"Skipping non-regular file found during walk: {full_path}")
                        continue
                except OSError as e:
                    logging.warning(f"Could not stat file during walk: {full_path}, error: {e}. Skipping.")
                    continue
                # --------------------------------------------------------------------------------------

                # --- Check combined ignore rules for the file ---
                try:
                     relative_path_to_base = full_path.relative_to(base_dir_for_rel_path)
                     relative_path_to_current = full_path.relative_to(dir_path)
                except ValueError:
                     logging.warning(f"Could not make file path relative during walk: {full_path}. Skipping.")
                     continue

                if (self.ignore_spec and self.ignore_spec.match_file(str(relative_path_to_base))) or \
                   (current_dir_ignore_spec and current_dir_ignore_spec.match_file(str(relative_path_to_current))):
                    # logging.debug(f"Ignoring '{relative_path_to_base}' in subdirectory due to ignore rules.")
                    continue
                # ---------------------------------------

                # --- Language filter ---
                if selected_language != "All Files":
                    if full_path.suffix.lower() not in allowed_extensions:
                        continue
                # ----------------------

                # --- Get content (includes binary check, empty check, read errors) ---
                file_content = self.get_file_content(full_path)
                if file_content is None: # None indicates skip (binary, empty, error)
                    continue
                # -----------------------------------------------------------------------

                # Use the already calculated relative path for output
                relative_path_output = relative_path_to_base

                ext = full_path.suffix[1:] if full_path.suffix else 'txt'
                output_content.append(f"\n--- File: {relative_path_output} ---") # Clearer header
                output_content.append(f"```{ext}")
                output_content.append(file_content)
                output_content.append("```\n")

                self.progress_value += progress_step
                # Avoid updating GUI too frequently, maybe update every N files or % increment?
                # For simplicity now, update every file. Needs threading for large dirs.
                self.progress_bar.setValue(int(min(100, self.progress_value)))
                QtWidgets.QApplication.processEvents()

    # --- generate_file method using lstat() ---
    def generate_file(self) -> None:
        """Generate markdown from selected items in the current list view."""
        output_content = []
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

        base_dir_for_output = self.working_dir
        # Use the ignore spec loaded relative to the base dir for consistency
        generation_ignore_spec = self.ignore_spec # Use ignore spec from current view
        total_files = 0
        current_lang = self.language_dropdown.currentText()
        current_exts = self.language_extensions[current_lang]

        # --- Counting Loop ---
        for path in selected_paths:
            try:
                # --- Use lstat() to check type without following symlinks ---
                st = path.lstat() # Get stat object for the path itself (link or target)
                is_regular_file = stat.S_ISREG(st.st_mode) # Check if mode is regular file
                is_regular_dir = stat.S_ISDIR(st.st_mode)   # Check if mode is directory
                # ----------------------------------------------------------

                if is_regular_file:
                    # Check ignores relative to the base output dir
                    try:
                         rel_path_str = str(path.relative_to(base_dir_for_output))
                         if generation_ignore_spec and generation_ignore_spec.match_file(rel_path_str):
                             continue
                    except ValueError: pass # Ignore if not relative

                    if not path.name.startswith('.') and not self.is_binary(path):
                        if current_lang == "All Files" or path.suffix.lower() in current_exts:
                            total_files += 1

                elif is_regular_dir:
                     # Check if the directory itself is ignored
                    try:
                         rel_path_str = str(path.relative_to(base_dir_for_output))
                         if generation_ignore_spec and generation_ignore_spec.match_file(rel_path_str + '/'):
                            continue
                    except ValueError: pass # Ignore if not relative

                     # Walk respecting ignores
                    current_dir_ignore_spec = load_ignore_patterns(path)
                    for root, dirs, files in os.walk(path, topdown=True, followlinks=False):
                        root_path = Path(root)
                        try:
                            root_rel_base = root_path.relative_to(base_dir_for_output)
                            root_rel_dir = root_path.relative_to(path)
                        except ValueError: continue # Skip if relative path fails

                        # Filter dirs based on combined ignores
                        dirs[:] = [d for d in dirs if not d.startswith('.') and
                                   (not generation_ignore_spec or not generation_ignore_spec.match_file(str(root_rel_base / d) + '/')) and
                                   (not current_dir_ignore_spec or not current_dir_ignore_spec.match_file(str(root_rel_dir / d) + '/'))]

                        for file_name in files:
                            count_path = root_path / file_name
                            try:
                                rel_base = count_path.relative_to(base_dir_for_output)
                                rel_dir = count_path.relative_to(path)
                            except ValueError: continue # Skip if relative path fails

                            # Combined ignore check for files
                            if (generation_ignore_spec and generation_ignore_spec.match_file(str(rel_base))) or \
                                (current_dir_ignore_spec and current_dir_ignore_spec.match_file(str(rel_dir))):
                                continue

                            # Check file type within walk using lstat for consistency
                            try:
                                file_st = count_path.lstat()
                                if not count_path.name.startswith('.') and stat.S_ISREG(file_st.st_mode) and not self.is_binary(count_path):
                                    if current_lang == "All Files" or count_path.suffix.lower() in current_exts:
                                         total_files += 1
                            except OSError: continue # Handle errors accessing file during count

            except (OSError, ValueError) as e: # Catch lstat errors or relative_to errors
                logging.warning(f"Cannot access or process {path} during pre-count: {e}")
                continue
        # --- End Counting Loop ---

        total_files = max(total_files, 1) # Avoid division by zero
        progress_step = 100.0 / total_files
        self.progress_value = 0.0
        self.progress_bar.setValue(0)
        # Show 0% initially
        self.progress_bar.setFormat(f"Processing... %p%") # Update format while processing


        logging.info(f"Starting generation from {base_dir_for_output}. Estimated files: {total_files}")

        # --- Processing Loop ---
        # Wrap processing in try/finally to ensure progress bar resets
        try:
            for full_path in selected_paths: # Now iterating over Path objects
                # logging.debug(f"Processing selected item: {full_path}") # Can be verbose
                try:
                    relative_path_to_base = full_path.relative_to(base_dir_for_output)

                    # --- Use lstat() again for processing check ---
                    st = full_path.lstat()
                    is_file = stat.S_ISREG(st.st_mode)
                    is_dir = stat.S_ISDIR(st.st_mode)
                    # --------------------------------------------

                    # Check top-level ignores again just in case
                    ignore_path_str = str(relative_path_to_base)
                    if is_dir: ignore_path_str += '/' # Add slash for dir ignore check

                    if generation_ignore_spec and generation_ignore_spec.match_file(ignore_path_str):
                         # logging.info(f"Skipping explicitly ignored item: {relative_path_to_base}")
                         continue

                    if is_file:
                        # Apply language filter here too
                        if current_lang != "All Files" and full_path.suffix.lower() not in current_exts:
                            continue

                        file_content = self.get_file_content(full_path)
                        if file_content is None: # None indicates skip (binary, empty, error)
                            continue

                        ext = full_path.suffix[1:] if full_path.suffix else 'txt'
                        output_content.append(f"\n--- File: {relative_path_to_base} ---")
                        output_content.append(f"```{ext}")
                        output_content.append(file_content)
                        output_content.append("```\n")

                        self.progress_value += progress_step
                        self.progress_bar.setValue(int(min(100, self.progress_value)))
                        QtWidgets.QApplication.processEvents() # NOTE: Still need threading here ideally

                    elif is_dir:
                        # Pass the base directory for relative path calculations inside
                        self.process_directory(full_path, output_content, progress_step, base_dir_for_output)
                    else: # Neither a regular file nor a regular dir
                         if stat.S_ISLNK(st.st_mode): # Check if symlink
                             logging.warning(f"Skipping '{relative_path_to_base}' as it is a symbolic link.")
                         elif not full_path.exists(): # Check existence only if not a symlink (avoids broken link warning)
                             logging.warning(f"Skipping '{relative_path_to_base}' as it no longer exists.")
                         else: # Other file types
                             logging.warning(f"Skipping '{relative_path_to_base}' as it is not a regular file or directory (mode: {st.st_mode:#o}).")


                except PermissionError as e:
                     logging.error(f"Permission denied accessing: {full_path}. Skipping item. {e}")
                     continue
                except OSError as e: # Catch lstat errors or other OS errors
                     logging.error(f"OS error processing item {full_path.name}: {e}", exc_info=False)
                     continue
                except ValueError as e: # Catch errors from relative_to() if path isn't under base_dir_for_output
                    logging.error(f"Path error processing {full_path} relative to {base_dir_for_output}: {e}")
                    continue
                except Exception as e:
                     logging.error(f"Unexpected error processing item {full_path.name}: {e}", exc_info=True)
                     continue
            # --- End Processing Loop for one item ---

            # Make sure progress bar reaches 100 if processing finished
            if selected_paths:
                 self.progress_bar.setValue(100)
                 self.progress_bar.setFormat("Saving...")
                 QtWidgets.QApplication.processEvents()


            if not output_content:
                 QtWidgets.QMessageBox.information(self, "Finished", "No processable content found in the selected items matching the filters.")
                 self.progress_bar.setValue(0)
                 self.progress_bar.setFormat("%p%") # Reset format
                 return

            # --- Save Dialog ---
            desktop_path = Path.home() / "Desktop"
            if not desktop_path.exists(): desktop_path = Path.home()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            initial_filename = f"concatenated_{base_dir_for_output.name}_{timestamp}.md"
            default_path = str(desktop_path / initial_filename)

            # Add options for better save dialog on some platforms (optional)
            options = QtWidgets.QFileDialog.Option.DontUseNativeDialog
            file_tuple = QtWidgets.QFileDialog.getSaveFileName(
                self, "Save Concatenated File", default_path, "Markdown Files (*.md);;All Files (*)",
                # options=options # Uncomment to force non-native dialog if needed
            )
            output_filename = file_tuple[0]

            if not output_filename:
                logging.info("Save operation cancelled by user.")
                # No need to reset progress bar here, finally block handles it
                return # Exit if save cancelled

            try:
                output_path = Path(output_filename)
                # Add a check to prevent overwriting the script itself (unlikely but possible)
                if '__file__' in globals() and output_path.resolve() == Path(__file__).resolve():
                     QtWidgets.QMessageBox.critical(self,"Error","Cannot overwrite the running script file!")
                     return

                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(f"# Concatenated Files from: {base_dir_for_output}\n")
                    f.write(f"# Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"# Selected language filter: {self.language_dropdown.currentText()}\n")
                    f.write("--- START OF CONTENT ---\n")
                    f.write('\n'.join(output_content)) # Use single newline join for code blocks
                    f.write("\n--- END OF CONTENT ---\n")
                QtWidgets.QMessageBox.information(self, "Success", f"File generated successfully:\n{output_filename}")
                logging.info(f"Successfully generated file: {output_filename}")
            except Exception as e:
                logging.error(f"Error writing output file {output_filename}: {e}", exc_info=True)
                QtWidgets.QMessageBox.critical(
                    self, "Error", f"Could not write output file:\n{output_filename}\n\n{e}"
                )

        finally:
             # Ensure progress bar is always reset after processing finishes or fails
             self.progress_bar.setValue(0)
             self.progress_bar.setFormat("%p%") # Reset default format


# --- Main block ---
if __name__ == "__main__":
    # Set Application details (optional, improves appearance on some systems)
    QtCore.QCoreApplication.setApplicationName("SOTA Concatenator")
    QtCore.QCoreApplication.setOrganizationName("YourOrg") # Replace if desired
    QtCore.QCoreApplication.setApplicationVersion("1.1")

    app = QtWidgets.QApplication(sys.argv)

    # --- Use QSettings to remember last directory (Optional UX improvement) ---
    settings = QtCore.QSettings("YourOrg", "SOTAConcatenator") # Use same names as above
    last_dir = settings.value("last_directory", str(Path.cwd()))
    # -----------------------------------------------------------------------

    selected_dir = QtWidgets.QFileDialog.getExistingDirectory(
        None, "Select Project Directory To Concatenate", last_dir # Start in last used dir
    )

    if selected_dir:
        working_dir = Path(selected_dir)
        settings.setValue("last_directory", selected_dir) # Save selected dir
    else:
        # If user cancels, default to the last used dir or CWD if none saved
        working_dir = Path(last_dir)
        logging.info(f"No directory selected, using last/default: {working_dir}")


    window = FileConcatenator(working_dir=working_dir)
    window.show()
    sys.exit(app.exec())