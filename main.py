import sys
import os
import logging
from pathlib import Path
from datetime import datetime

from PyQt6 import QtCore, QtWidgets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


class FileConcatenator(QtWidgets.QMainWindow):
    """
    A PyQt6-based graphical application to select and concatenate multiple files
    into a single markdown file. Provides language-based filtering, search functionality,
    and a preview of progress via a progress bar.
    """
    def __init__(self, working_dir: Path = None) -> None:
        super().__init__()
        self.working_dir = working_dir or Path.cwd()
        self.setWindowTitle("SOTA File Concatenator")
        self.resize(700, 500)

        # Define language extensions
        self.language_extensions = {
            "All Files": ["*"],
            "Python": [".py", ".pyw", ".pyx"],
            "JavaScript": [".js", ".jsx", ".ts", ".tsx"],
            "Java": [".java", ".class", ".jar"],
            "C/C++": [".c", ".cpp", ".h", ".hpp"],
            "Ruby": [".rb", ".rake"],
            "PHP": [".php"],
            "Go": [".go"],
            "Rust": [".rs"],
            "Swift": [".swift"],
            "HTML/CSS": [".html", ".htm", ".css"],
        }

        # Dictionary to hold checkboxes by item name
        self.checkboxes = {}
        # Variable to track progress (as float)
        self.progress_value = 0.0

        self.init_ui()
        self.populate_checkboxes()

    def init_ui(self) -> None:
        """Create and place all PyQt6 widgets."""
        central_widget = QtWidgets.QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QtWidgets.QVBoxLayout(central_widget)

        # Top filter/search layout
        top_layout = QtWidgets.QHBoxLayout()

        language_label = QtWidgets.QLabel("Language Filter:")
        top_layout.addWidget(language_label)

        self.language_dropdown = QtWidgets.QComboBox()
        self.language_dropdown.addItems(list(self.language_extensions.keys()))
        self.language_dropdown.setCurrentText("All Files")
        top_layout.addWidget(self.language_dropdown)
        self.language_dropdown.currentTextChanged.connect(self.refresh_files)

        search_label = QtWidgets.QLabel("Search:")
        top_layout.addWidget(search_label)

        self.search_entry = QtWidgets.QLineEdit()
        top_layout.addWidget(self.search_entry)
        self.search_entry.textChanged.connect(self.refresh_files)

        top_layout.addStretch()
        main_layout.addLayout(top_layout)

        # Scroll area for file/directory checkboxes
        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_widget = QtWidgets.QWidget()
        self.checkbox_layout = QtWidgets.QVBoxLayout(self.scroll_widget)
        self.scroll_area.setWidget(self.scroll_widget)
        main_layout.addWidget(self.scroll_area)

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
        bottom_layout.addWidget(self.progress_bar)

        self.btn_generate = QtWidgets.QPushButton("Generate File")
        self.btn_generate.clicked.connect(self.generate_file)
        bottom_layout.addWidget(self.btn_generate)

        main_layout.addLayout(bottom_layout)

    def populate_checkboxes(self) -> None:
        """Populate the scrollable area with file and directory checkboxes filtered by language and search."""
        # Clear existing widgets
        while self.checkbox_layout.count():
            child = self.checkbox_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.checkboxes.clear()

        current_dir = self.working_dir
        selected_language = self.language_dropdown.currentText()
        allowed_extensions = self.language_extensions.get(selected_language, ["*"])
        search_text = self.search_entry.text().lower().strip()

        all_items = list(current_dir.iterdir())
        directories = []
        files = []
        # Avoid the script file itself
        script_name = Path(__file__).name if '__file__' in globals() else ""

        for item in all_items:
            if item.name.startswith('.') or (script_name and item.name == script_name):
                continue
            if search_text and search_text not in item.name.lower():
                continue

            if item.is_dir():
                directories.append(item)
            else:
                # Check if file is binary by trying to read a portion
                try:
                    with item.open('r', encoding='utf-8', errors='strict') as f:
                        f.read(1024)
                except UnicodeDecodeError:
                    logging.warning(f"Skipping binary file: {item}")
                    continue
                except Exception as e:
                    logging.error(f"Error checking file {item}: {e}")
                    continue

                if selected_language != "All Files":
                    if item.suffix.lower() not in allowed_extensions:
                        continue
                files.append(item)

        # Sort directories and files by name (case-insensitive)
        directories.sort(key=lambda p: p.name.lower())
        files.sort(key=lambda p: p.name.lower())

        # Create directory checkboxes if any
        if directories:
            lbl_dirs = QtWidgets.QLabel("Directories:")
            font = lbl_dirs.font()
            font.setBold(True)
            lbl_dirs.setFont(font)
            self.checkbox_layout.addWidget(lbl_dirs)

            for directory in directories:
                cb = QtWidgets.QCheckBox(directory.name)
                self.checkbox_layout.addWidget(cb)
                self.checkboxes[directory.name] = cb

        # Create file checkboxes if any
        if files:
            if directories:
                separator = QtWidgets.QFrame()
                separator.setFrameShape(QtWidgets.QFrame.Shape.HLine)
                separator.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
                self.checkbox_layout.addWidget(separator)

            lbl_files = QtWidgets.QLabel("Files:")
            font = lbl_files.font()
            font.setBold(True)
            lbl_files.setFont(font)
            self.checkbox_layout.addWidget(lbl_files)

            for file_item in files:
                cb = QtWidgets.QCheckBox(file_item.name)
                self.checkbox_layout.addWidget(cb)
                self.checkboxes[file_item.name] = cb

        self.checkbox_layout.addStretch()

    def refresh_files(self) -> None:
        """Refresh the list of file/directory checkboxes."""
        self.populate_checkboxes()

    def select_all(self) -> None:
        """Select all checkboxes."""
        for cb in self.checkboxes.values():
            cb.setChecked(True)

    def deselect_all(self) -> None:
        """Deselect all checkboxes."""
        for cb in self.checkboxes.values():
            cb.setChecked(False)

    def get_file_content(self, filepath: Path) -> str:
        """
        Safely read the content of a file using UTF-8 encoding, skipping binary/unreadable files.
        """
        try:
            return filepath.read_text(encoding='utf-8', errors='strict')
        except UnicodeDecodeError:
            logging.warning(f"Skipping binary file: {filepath}")
            return ""
        except Exception as e:
            logging.error(f"Error reading file {filepath}: {e}", exc_info=True)
            return f"Error reading file: {str(e)}"

    def process_directory(self, dir_path: Path, output_content: list, progress_step: float) -> None:
        """
        Recursively process a directory by appending file contents (that match the selected language filter)
        to output_content and update the progress bar accordingly.
        """
        selected_language = self.language_dropdown.currentText()
        allowed_extensions = self.language_extensions[selected_language]

        for root, _, files in os.walk(dir_path):
            root_path = Path(root)
            for file_name in files:
                if file_name.startswith('.'):
                    continue
                if selected_language != "All Files":
                    if Path(file_name).suffix.lower() not in allowed_extensions:
                        continue

                full_path = root_path / file_name
                file_content = self.get_file_content(full_path)
                if not file_content:
                    continue

                try:
                    relative_path = full_path.relative_to(self.working_dir)
                except ValueError:
                    relative_path = full_path
                ext = full_path.suffix[1:] if full_path.suffix else 'txt'
                output_content.append(f"\n{relative_path}")
                output_content.append(f"```{ext}")
                output_content.append(file_content)
                output_content.append("```\n")

                self.progress_value += progress_step
                self.progress_bar.setValue(int(min(100, self.progress_value)))
                QtWidgets.QApplication.processEvents()

    def generate_file(self) -> None:
        """
        Generate a markdown file containing the concatenated contents of selected files and directories.
        Updates a progress bar during processing and shows a save dialog at the end.
        """
        output_content = []
        current_dir = self.working_dir
        items_to_process = [name for name, cb in self.checkboxes.items() if cb.isChecked()]

        if not items_to_process:
            QtWidgets.QMessageBox.warning(
                self, "No Selection", "Please select at least one file or directory."
            )
            return

        # Approximate the total number of files for progress tracking
        total_files = 0
        for item_name in items_to_process:
            full_path = current_dir / item_name
            if full_path.is_file():
                total_files += 1
            elif full_path.is_dir():
                for path in full_path.rglob('*'):
                    if path.is_file():
                        total_files += 1

        total_files = max(total_files, 1)
        progress_step = 100.0 / total_files
        self.progress_value = 0.0
        self.progress_bar.setValue(0)

        for item_name in items_to_process:
            full_path = current_dir / item_name
            if full_path.is_file():
                file_content = self.get_file_content(full_path)
                if not file_content:
                    continue
                ext = full_path.suffix[1:] if full_path.suffix else 'txt'
                output_content.append(f"\n{full_path.name}")
                output_content.append(f"```{ext}")
                output_content.append(file_content)
                output_content.append("```\n")

                self.progress_value += progress_step
                self.progress_bar.setValue(int(min(100, self.progress_value)))
                QtWidgets.QApplication.processEvents()

            elif full_path.is_dir():
                self.process_directory(full_path, output_content, progress_step)

        # Specify the desktop as the default save directory
        desktop_path = Path.home() / "Desktop"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        initial_filename = f"concatenated_{timestamp}.md"
        default_path = str(desktop_path / initial_filename)

        # Call getSaveFileName without the options parameter.
        file_tuple = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save Concatenated File",
            default_path,
            "Markdown Files (*.md);;All Files (*)",
        )
        output_filename = file_tuple[0]
        if not output_filename:
            self.progress_bar.setValue(0)
            return

        try:
            with open(output_filename, 'w', encoding='utf-8') as f:
                f.write('\n'.join(output_content))
            QtWidgets.QMessageBox.information(
                self, "Success", f"File generated: {output_filename}"
            )
            logging.info(f"Successfully generated file: {output_filename}")
        except Exception as e:
            logging.error(f"Error writing output file {output_filename}: {e}", exc_info=True)
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Could not write output file:\n{e}"
            )

        self.progress_bar.setValue(0)


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    # Ask the user to choose a working directory. If no selection, default to current working directory.
    selected_dir = QtWidgets.QFileDialog.getExistingDirectory(
        None,
        "Select Directory",
        str(Path.cwd())
    )
    if selected_dir:
        working_dir = Path(selected_dir)
    else:
        working_dir = Path.cwd()

    window = FileConcatenator(working_dir=working_dir)
    window.show()
    sys.exit(app.exec())