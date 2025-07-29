"""Main application window for the Source Stitcher application."""

import logging
import os
import stat
from pathlib import Path
from typing import List, Optional, Set, Tuple

from PyQt6 import QtCore, QtGui, QtWidgets

from .config import FilterSettings, GenerationOptions, WorkerConfig
from .file_utils import build_filter_sets, load_ignore_patterns, load_global_gitignore, matches_file_type
from .language_definitions import get_language_extensions
from .ui.dialogs import SaveFileDialog
from .worker import GeneratorWorker


class FileConcatenator(QtWidgets.QMainWindow):
    """
    A PyQt6-based graphical application for concatenating multiple files with language filtering.
    """

    PATH_ROLE = QtCore.Qt.ItemDataRole.UserRole + 1
    LANGUAGE_ROLE = QtCore.Qt.ItemDataRole.UserRole + 2

    def __init__(self, working_dir: Optional[Path] = None) -> None:
        super().__init__()
        self.initial_base_dir = (working_dir or Path.cwd()).resolve()
        self.working_dir = self.initial_base_dir
        self.setWindowTitle(f"SOTA Concatenator - [{self.working_dir.name}]")
        self.resize(700, 650)

        self.ignore_spec = load_ignore_patterns(self.working_dir)
        self.global_ignore_spec = load_global_gitignore()
        self.icon_provider = QtWidgets.QFileIconProvider()

        self.worker_thread: Optional[QtCore.QThread] = None
        self.worker: Optional[GeneratorWorker] = None
        self.is_generating = False

        # Load language extensions
        self.language_extensions = get_language_extensions()

        # Pre-compile all known extensions and filenames for fast lookups
        self.ALL_EXTENSIONS, self.ALL_FILENAMES = build_filter_sets(
            self.language_extensions
        )

        # Initialize save dialog
        self.save_dialog = SaveFileDialog(self)

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
        style = self.style()
        if style is not None:
            self.btn_up.setIcon(
                style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ArrowUp)
            )
        self.btn_up.setToolTip("Go to Parent Directory (Alt+Up)")
        self.btn_up.setShortcut(QtGui.QKeySequence("Alt+Up"))
        self.btn_up.clicked.connect(self.go_up_directory)
        self.btn_up.setFixedWidth(
            self.btn_up.fontMetrics().horizontalAdvance(" Up ") * 2
        )
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
        self.file_tree_widget.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.file_tree_widget.itemDoubleClicked.connect(self.handle_item_double_click)
        self.file_tree_widget.itemExpanded.connect(self.populate_children)
        self.file_tree_widget.itemChanged.connect(self.handle_check_change)
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

    def get_selected_filter_sets(self) -> Tuple[Set[str], Set[str], bool]:
        """Get the compiled sets of selected extensions and filenames."""
        selected_exts: Set[str] = set()
        selected_names: Set[str] = set()
        handle_other = False

        for i in range(self.language_list_widget.count()):
            item = self.language_list_widget.item(i)
            assert item is not None
            if item.checkState() == QtCore.Qt.CheckState.Checked:
                language_name = item.data(self.LANGUAGE_ROLE)
                if language_name == "Other Text Files":
                    handle_other = True
                    continue

                if language_name in self.language_extensions:
                    for e in self.language_extensions[language_name]:
                        (selected_exts if e.startswith(".") else selected_names).add(
                            e.lower()
                        )

        return selected_exts, selected_names, handle_other

    def get_selected_language_names(self) -> List[str]:
        """Get names of selected language types for display purposes."""
        selected_names: List[str] = []

        for i in range(self.language_list_widget.count()):
            item = self.language_list_widget.item(i)
            assert item is not None
            if item.checkState() == QtCore.Qt.CheckState.Checked:
                language_name = item.data(self.LANGUAGE_ROLE)
                selected_names.append(language_name)

        return selected_names

    def select_all_languages(self) -> None:
        """Select all language types."""
        if self.is_generating:
            return
        for i in range(self.language_list_widget.count()):
            item = self.language_list_widget.item(i)
            assert item is not None
            item.setCheckState(QtCore.Qt.CheckState.Checked)

    def deselect_all_languages(self) -> None:
        """Deselect all language types."""
        if self.is_generating:
            return
        for i in range(self.language_list_widget.count()):
            item = self.language_list_widget.item(i)
            assert item is not None
            item.setCheckState(QtCore.Qt.CheckState.Unchecked)

    def select_code_only(self) -> None:
        """Select only programming language categories."""
        if self.is_generating:
            return
        code_categories = {
            "Python",
            "JavaScript/TypeScript",
            "Web Frontend",
            "Java/Kotlin",
            "C/C++",
            "C#/.NET",
            "Ruby",
            "PHP",
            "Go",
            "Rust",
            "Swift/Objective-C",
            "Shell Scripts",
        }
        for i in range(self.language_list_widget.count()):
            item = self.language_list_widget.item(i)
            assert item is not None
            language_name = item.data(self.LANGUAGE_ROLE)
            if language_name in code_categories:
                item.setCheckState(QtCore.Qt.CheckState.Checked)
            else:
                item.setCheckState(QtCore.Qt.CheckState.Unchecked)

    def select_docs_config(self) -> None:
        """Select documentation and configuration categories."""
        if self.is_generating:
            return
        docs_config_categories = {
            "Documentation",
            "Config & Data",
            "DevOps & CI",
            "Version Control",
            "Build & Package",
            "Other Text Files",
        }
        for i in range(self.language_list_widget.count()):
            item = self.language_list_widget.item(i)
            assert item is not None
            language_name = item.data(self.LANGUAGE_ROLE)
            if language_name in docs_config_categories:
                item.setCheckState(QtCore.Qt.CheckState.Checked)
            else:
                item.setCheckState(QtCore.Qt.CheckState.Unchecked)

    def update_ui_state(self) -> None:
        """Updates UI elements based on the current state."""
        try:
            display_path = self.working_dir.relative_to(self.initial_base_dir)
            title_path = (
                f".../{display_path}"
                if display_path != Path(".")
                else self.initial_base_dir.name
            )
        except ValueError:
            title_path = str(self.working_dir)
        self.setWindowTitle(f"SOTA Concatenator - [{title_path}]")
        self.current_path_label.setText(str(self.working_dir))
        self.current_path_label.setCursorPosition(0)
        is_root = self.working_dir.parent == self.working_dir
        self.btn_up.setEnabled(not is_root and not self.is_generating)

    def set_controls_enabled(self, enabled: bool) -> None:
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

    def add_dir_node(
        self, parent_item: Optional[QtWidgets.QTreeWidgetItem], path: Path
    ) -> QtWidgets.QTreeWidgetItem:
        """Adds a directory node to the tree."""
        node = QtWidgets.QTreeWidgetItem([path.name])
        node.setFlags(
            node.flags()
            | QtCore.Qt.ItemFlag.ItemIsUserCheckable
        )
        node.setCheckState(0, QtCore.Qt.CheckState.Unchecked)
        node.setData(0, self.PATH_ROLE, path)
        node.setIcon(
            0, self.icon_provider.icon(QtWidgets.QFileIconProvider.IconType.Folder)
        )

        # Show the expander arrow without a fake child
        node.setChildIndicatorPolicy(
            QtWidgets.QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator
        )

        if parent_item:
            parent_item.addChild(node)
        else:
            self.file_tree_widget.addTopLevelItem(node)
        return node

    def add_file_node(
        self, parent_item: Optional[QtWidgets.QTreeWidgetItem], path: Path
    ) -> None:
        """Adds a file node to the tree."""
        try:
            qfileinfo = QtCore.QFileInfo(str(path))
            specific_icon = self.icon_provider.icon(qfileinfo)
        except Exception:
            specific_icon = QtGui.QIcon()

        item_icon = (
            specific_icon
            if not specific_icon.isNull()
            else self.icon_provider.icon(QtWidgets.QFileIconProvider.IconType.File)
        )
        item = QtWidgets.QTreeWidgetItem([path.name])
        item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, QtCore.Qt.CheckState.Unchecked)
        item.setData(0, self.PATH_ROLE, path)
        item.setIcon(0, item_icon)

        if parent_item:
            parent_item.addChild(item)
        else:
            self.file_tree_widget.addTopLevelItem(item)

    @QtCore.pyqtSlot(QtWidgets.QTreeWidgetItem)
    def populate_children(self, item: QtWidgets.QTreeWidgetItem) -> None:
        """Populates the children of a directory item when it's expanded."""
        # Already populated?
        if item.childCount() > 0:
            return

        blocked = self.file_tree_widget.signalsBlocked()
        self.file_tree_widget.blockSignals(True)

        path: Path | None = item.data(0, self.PATH_ROLE)
        if path and path.is_dir():
            self.populate_directory(path, item)

        # propagate check-state to the new children
        state = item.checkState(0)
        if state != QtCore.Qt.CheckState.PartiallyChecked:
            self._set_children_check_state(item, state)
        self._update_parent_check_state(item)

        self.file_tree_widget.blockSignals(blocked)

        # update ancestors
        parent = item.parent()
        while parent:
            self._update_parent_check_state(parent)
            parent = parent.parent()

    def populate_directory(
        self, directory: Path, parent_item: Optional[QtWidgets.QTreeWidgetItem]
    ) -> None:
        """Populate the tree widget with files and directories for one level, rejecting paths outside root."""
        selected_exts, selected_names, handle_other = self.get_selected_filter_sets()
        search_text = self.search_entry.text().lower().strip()

        try:
            entries = []
            for entry in os.scandir(directory):
                item_path = Path(entry.path)
                try:
                    resolved = item_path.resolve()
                    if not str(resolved).startswith(str(self.working_dir.resolve())):
                        logging.warning(
                            f"Rejected path outside project root: {resolved}"
                        )
                        continue
                except Exception as e:
                    logging.warning(f"Error resolving path {item_path}: {e}")
                    continue

                # Use relative path for ignore checks if possible
                try:
                    relative_path = item_path.relative_to(self.working_dir)
                    relative_path_str_for_ignore = str(relative_path)
                except ValueError:
                    relative_path_str_for_ignore = entry.name

                if entry.is_dir(
                    follow_symlinks=False
                ) and not relative_path_str_for_ignore.endswith("/"):
                    relative_path_str_for_ignore += "/"

                if self.ignore_spec and self.ignore_spec.match_file(
                    relative_path_str_for_ignore
                ):
                    continue

                if entry.name.startswith("."):
                    continue

                if search_text and search_text not in entry.name.lower():
                    continue

                try:
                    if not os.access(entry.path, os.R_OK):
                        continue
                    if entry.is_dir() and not os.access(entry.path, os.X_OK):
                        continue
                except OSError:
                    continue

                entries.append((entry, item_path))

            entries.sort(
                key=lambda x: (not x[0].is_dir(follow_symlinks=True), x[0].name.lower())
            )

            for entry, item_path in entries:
                if entry.is_dir(follow_symlinks=True):
                    self.add_dir_node(parent_item, item_path)
                elif entry.is_file(follow_symlinks=True):
                    if not (
                        selected_exts or selected_names or handle_other
                    ) or matches_file_type(
                        item_path,
                        selected_exts,
                        selected_names,
                        self.ALL_EXTENSIONS,
                        self.ALL_FILENAMES,
                        handle_other,
                    ):
                        self.add_file_node(parent_item, item_path)

        except PermissionError as e:
            logging.error(f"Permission denied accessing directory: {directory}. {e}")
            if parent_item:
                parent_item.setDisabled(True)
        except Exception as e:
            logging.error(f"Error listing directory {directory}: {e}", exc_info=True)
            if parent_item:
                parent_item.setDisabled(True)

    def refresh_files(self) -> None:
        """Refresh list (reload ignores)."""
        if self.is_generating:
            return
        self.ignore_spec = load_ignore_patterns(self.working_dir)
        self.populate_file_list()

    def handle_item_double_click(
        self, item: QtWidgets.QTreeWidgetItem, column: int
    ) -> None:
        """Navigate into directory."""
        if self.is_generating:
            return
        path_data = item.data(0, self.PATH_ROLE)
        if path_data and isinstance(path_data, Path):
            try:
                st = os.stat(path_data)
                if stat.S_ISDIR(st.st_mode):
                    _ = list(os.scandir(path_data))
                    self.working_dir = path_data.resolve()
                    logging.info(f"Navigated into directory: {self.working_dir}")
                    self.refresh_files()
                    self.search_entry.clear()
            except PermissionError:
                logging.warning(
                    f"Permission denied trying to navigate into {path_data}"
                )
                QtWidgets.QMessageBox.warning(
                    self,
                    "Access Denied",
                    f"Cannot open directory:\n{path_data.name}\n\nPermission denied.",
                )
            except FileNotFoundError:
                logging.warning(
                    f"Directory not found (deleted?) on double click: {path_data}"
                )
                QtWidgets.QMessageBox.warning(
                    self, "Not Found", f"Directory not found:\n{path_data.name}"
                )
                self.refresh_files()
            except Exception as e:
                logging.error(
                    f"Error navigating into directory {path_data}: {e}", exc_info=True
                )
                QtWidgets.QMessageBox.warning(
                    self,
                    "Navigation Error",
                    f"Could not open directory:\n{path_data.name}\n\n{e}",
                )

    def go_up_directory(self) -> None:
        """Navigate up."""
        if self.is_generating:
            return
        parent_dir = self.working_dir.parent
        if parent_dir != self.working_dir:
            try:
                _ = list(os.scandir(parent_dir))
                self.working_dir = parent_dir.resolve()
                logging.info(f"Navigated up to directory: {self.working_dir}")
                self.refresh_files()
                self.search_entry.clear()
            except PermissionError:
                logging.warning(
                    f"Permission denied trying to navigate up to {parent_dir}"
                )
                QtWidgets.QMessageBox.warning(
                    self,
                    "Access Denied",
                    f"Cannot open parent directory:\n{parent_dir}\n\nPermission denied.",
                )
            except FileNotFoundError:
                logging.warning(f"Parent directory not found (deleted?): {parent_dir}")
                QtWidgets.QMessageBox.warning(
                    self, "Not Found", f"Parent directory not found:\n{parent_dir}"
                )
            except Exception as e:
                logging.error(
                    f"Error navigating up to directory {parent_dir}: {e}", exc_info=True
                )
                QtWidgets.QMessageBox.warning(
                    self,
                    "Navigation Error",
                    f"Could not open parent directory:\n{parent_dir}\n\n{e}",
                )

    def select_all(self) -> None:
        """Select all checkable items."""
        if self.is_generating:
            return
        self._set_all_items_checked(True)

    def deselect_all(self) -> None:
        """Deselect all checkable items."""
        if self.is_generating:
            return
        self._set_all_items_checked(False)

    def _set_all_items_checked(self, checked: bool) -> None:
        """Recursively set the checked state of all items."""
        check_state = (
            QtCore.Qt.CheckState.Checked if checked else QtCore.Qt.CheckState.Unchecked
        )
        for i in range(self.file_tree_widget.topLevelItemCount()):
            item = self.file_tree_widget.topLevelItem(i)
            if item is not None:
                self._set_item_checked_recursive(item, check_state)

    def _set_item_checked_recursive(
        self, item: QtWidgets.QTreeWidgetItem, check_state: QtCore.Qt.CheckState
    ) -> None:
        """Recursively set the checked state of an item and its children."""
        if item.flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable:
            item.setCheckState(0, check_state)
        for i in range(item.childCount()):
            child = item.child(i)
            if child is not None:
                self._set_item_checked_recursive(child, check_state)

    def handle_check_change(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        if column != 0:
            return
        state = item.checkState(0)
        if state != QtCore.Qt.CheckState.PartiallyChecked:
            self._set_children_check_state(item, state)
        parent = item.parent()
        while parent:
            self._update_parent_check_state(parent)
            parent = parent.parent()

    def _set_children_check_state(
        self, item: QtWidgets.QTreeWidgetItem, state: QtCore.Qt.CheckState
    ) -> None:
        for i in range(item.childCount()):
            child = item.child(i)
            if child is not None:
                if child.flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable:
                    child.setCheckState(0, state)
                self._set_children_check_state(child, state)

    def _update_parent_check_state(self, parent: QtWidgets.QTreeWidgetItem) -> None:
        checked_count = 0
        total_count = 0
        has_partial = False
        for i in range(parent.childCount()):
            child = parent.child(i)
            if child is not None and child.flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable:
                total_count += 1
                child_state = child.checkState(0)
                if child_state == QtCore.Qt.CheckState.Checked:
                    checked_count += 1
                elif child_state == QtCore.Qt.CheckState.PartiallyChecked:
                    has_partial = True
        if total_count == 0:
            return
        if checked_count == total_count and not has_partial:
            parent.setCheckState(0, QtCore.Qt.CheckState.Checked)
        elif checked_count == 0 and not has_partial:
            parent.setCheckState(0, QtCore.Qt.CheckState.Unchecked)
        else:
            parent.setCheckState(0, QtCore.Qt.CheckState.PartiallyChecked)

    def _collect_selected_paths(self, item: QtWidgets.QTreeWidgetItem) -> List[Path]:
        """Recursively collect all checked file paths from the tree, rejecting paths outside project root."""
        paths: List[Path] = []
        item_path = item.data(0, self.PATH_ROLE)
        if item_path and isinstance(item_path, Path):
            try:
                resolved = item_path.resolve()
                # Reject if outside project root using proper path comparison
                try:
                    if not resolved.is_relative_to(self.working_dir.resolve()):
                        logging.warning(
                            f"Rejected path outside project root: {resolved}"
                        )
                        return paths
                except AttributeError:
                    # Fallback for Python < 3.9 - use Path.parts for comparison
                    try:
                        working_dir_parts = self.working_dir.resolve().parts
                        resolved_parts = resolved.parts
                        if (
                            resolved_parts[: len(working_dir_parts)]
                            != working_dir_parts
                        ):
                            logging.warning(
                                f"Rejected path outside project root (fallback): {resolved}"
                            )
                            return paths
                    except Exception as e:
                        logging.warning(f"Error in path comparison: {e}")
                        return paths
            except Exception as e:
                logging.warning(f"Error resolving path {item_path}: {e}")
                return paths
            if item.checkState(0) == QtCore.Qt.CheckState.Checked:
                paths.append(item_path)
            else:
                for i in range(item.childCount()):
                    child = item.child(i)
                    if child is not None:
                        paths.extend(self._collect_selected_paths(child))
        return paths

    def start_generate_file(self) -> None:
        """Initiates the file generation process in a background thread."""
        if self.is_generating:
            logging.warning("Generation process already running.")
            return

        selected_exts, selected_names, handle_other = self.get_selected_filter_sets()
        if not selected_exts and not selected_names and not handle_other:
            QtWidgets.QMessageBox.warning(
                self, "No File Types", "Please select at least one file type."
            )
            return

        selected_paths = self._collect_selected_paths_recursive()

        if not selected_paths:
            QtWidgets.QMessageBox.warning(
                self, "No Selection", "Please select at least one file or directory."
            )
            return

        self.is_generating = True
        self.set_controls_enabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setFormat("Starting...")

        # Create configuration objects
        filter_settings = FilterSettings(
            selected_extensions=selected_exts,
            selected_filenames=selected_names,
            all_known_extensions=self.ALL_EXTENSIONS,
            all_known_filenames=self.ALL_FILENAMES,
            handle_other_text_files=handle_other,
            ignore_spec=self.ignore_spec,
            global_ignore_spec=self.global_ignore_spec,
            search_text=self.search_entry.text(),
        )

        generation_options = GenerationOptions(
            selected_paths=selected_paths, base_directory=self.working_dir
        )

        worker_config = WorkerConfig(
            filter_settings=filter_settings, generation_options=generation_options
        )

        self.worker_thread = QtCore.QThread()
        self.worker = GeneratorWorker(worker_config)
        assert self.worker is not None
        assert self.worker_thread is not None
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

    def _collect_selected_paths_recursive(self) -> List[Path]:
        """Collect all selected paths from the tree widget."""
        paths: List[Path] = []
        for i in range(self.file_tree_widget.topLevelItemCount()):
            item = self.file_tree_widget.topLevelItem(i)
            if item is not None:
                paths.extend(self._collect_selected_paths(item))
            else:
                logging.warning(f"Null item at index {i} in top level items")
        return paths

    @QtCore.pyqtSlot(int)
    def handle_pre_count(self, total_files: int) -> None:
        """Slot to handle the pre_count_finished signal."""
        logging.info(f"Received pre-count: {total_files}")
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")

    @QtCore.pyqtSlot(int)
    def handle_progress_update(self, value: int) -> None:
        """Slot to handle the progress_updated signal."""
        self.progress_bar.setValue(value)

    @QtCore.pyqtSlot(str)
    def handle_status_update(self, message: str) -> None:
        """Slot to handle the status_updated signal."""
        self.progress_bar.setFormat(message + " %p%")

    @QtCore.pyqtSlot(str, str)
    def handle_generation_finished(
        self, temp_file_path: str, error_message: str
    ) -> None:
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
                QtWidgets.QMessageBox.warning(
                    self, "Generation Error", f"An error occurred:\n{error_message}"
                )
        elif not temp_file_path:
            QtWidgets.QMessageBox.information(
                self,
                "Finished",
                "No processable content found in the selected items matching the filters.",
            )
        else:
            try:
                selected_language_names = self.get_selected_language_names()
                self.save_dialog.save_generated_file(
                    temp_file_path, self.working_dir, selected_language_names
                )
            except Exception as e:
                error_message = str(e)
                QtWidgets.QMessageBox.critical(
                    self,
                    "Error Saving File",
                    f"Failed to save output file: {error_message}",
                )

    def generation_cleanup(self) -> None:
        """Slot called when the thread finishes, regardless of reason."""
        logging.info("Generator thread finished signal received. Cleaning up.")
        self.worker = None
        self.worker_thread = None
        self.is_generating = False
        self.set_controls_enabled(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")

    def cancel_generation(self) -> None:
        """Requests cancellation of the running worker."""
        if self.worker:
            logging.info("Cancel button clicked. Requesting worker cancellation.")
            self.worker.cancel()
            self.btn_cancel.setEnabled(False)
            self.progress_bar.setFormat("Cancelling...")
        else:
            logging.warning("Cancel clicked but no worker active.")

    def closeEvent(self, event: Optional[QtGui.QCloseEvent]) -> None:
        """Handle window close event, ensuring worker thread is stopped."""
        if event is None:
            return
        if self.is_generating and self.worker_thread and self.worker_thread.isRunning():
            reply = QtWidgets.QMessageBox.question(
                self,
                "Confirm Exit",
                "A generation task is running. Are you sure you want to exit?",
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No,
            )
            if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                logging.info(
                    "Window close requested during generation. Attempting cancellation."
                )
                if self.worker:
                    self.worker.cancel()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()