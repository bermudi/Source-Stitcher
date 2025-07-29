"""Dialog utilities for the Source Stitcher application."""

import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

from PyQt6 import QtCore, QtWidgets
from atomicwrites import atomic_write  # type: ignore[import-untyped]


class SaveFileDialog:
    """Handles the save file dialog and file writing operations."""
    
    def __init__(self, parent_window):
        self.parent = parent_window
    
    def save_generated_file(self, temp_file_path: str, working_dir: Path, selected_language_names: list) -> None:
        """Handles the save file dialog and writing the output."""
        # Try to find Desktop, with multiple fallback strategies
        desktop_path = self._find_desktop_path()
        
        # Generate filename based on the current working directory name
        initial_filename = self._generate_filename(working_dir, selected_language_names)
        default_path = desktop_path / initial_filename

        logging.info(f"Save dialog defaulting to: {default_path}")

        # Make the dialog application modal
        file_dialog = QtWidgets.QFileDialog(
            self.parent,
            "Save Concatenated File",
            str(default_path),
            "Markdown Files (*.md);;Text Files (*.txt);;All Files (*)",
        )
        file_dialog.setFileMode(QtWidgets.QFileDialog.FileMode.AnyFile)
        file_dialog.setAcceptMode(QtWidgets.QFileDialog.AcceptMode.AcceptSave)
        file_dialog.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
        
        if file_dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            output_filename = file_dialog.selectedFiles()[0]
        else:
            output_filename = ""

        if not output_filename:
            logging.info("Save operation cancelled by user.")
            QtWidgets.QMessageBox.information(
                self.parent, "Cancelled", "Save operation cancelled."
            )
            return

        try:
            self._write_output_file(output_filename, temp_file_path, working_dir, selected_language_names)
        except Exception as e:
            logging.error(
                f"Error writing output file {output_filename}: {e}", exc_info=True
            )
            QtWidgets.QMessageBox.critical(
                self.parent, "Error", f"Could not write output file:\n{output_filename}\n\n{e}"
            )
    
    def _find_desktop_path(self) -> Path:
        """Find the desktop directory with fallbacks."""
        possible_desktop_paths = [
            Path.home() / "Desktop",
            Path.home() / "desktop",  # Linux sometimes uses lowercase
            Path.home() / "Bureau",  # French systems
            Path.home() / "Escritorio",  # Spanish systems
            Path.home() / "Área de Trabalho",  # Portuguese systems
        ]

        for path in possible_desktop_paths:
            if path.exists() and path.is_dir():
                return path

        # Fallback to home directory if no desktop found
        logging.info("Desktop directory not found, using home directory as default")
        return Path.home()
    
    def _generate_filename(self, working_dir: Path, selected_language_names: list) -> str:
        """Generate a filename based on directory and selected languages."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dir_name = working_dir.name if working_dir.name else "files"

        # Include selected language types in filename (abbreviated)
        if len(selected_language_names) <= 2:
            lang_suffix = "_".join(selected_language_names)
        elif len(selected_language_names) <= 4:
            lang_suffix = "_".join(selected_language_names[:3]) + "_etc"
        else:
            lang_suffix = "mixed_types"

        # Clean up language suffix for filename (remove problematic characters)
        lang_suffix = (
            lang_suffix.replace("/", "_").replace("&", "and").replace(" ", "_")
        )

        initial_filename = f"{dir_name}_{lang_suffix}_{timestamp}.md"

        # Ensure filename is not too long (some filesystems have limits)
        if len(initial_filename) > 100:
            initial_filename = f"concatenated_{dir_name}_{timestamp}.md"
        
        return initial_filename
    
    def _write_output_file(self, output_filename: str, temp_file_path: str, working_dir: Path, selected_language_names: list) -> None:
        """Write the final output file."""
        output_path = Path(output_filename)

        # Prevent overwriting the running script
        if (
            "__file__" in globals()
            and output_path.resolve() == Path(__file__).resolve()
        ):
            QtWidgets.QMessageBox.critical(
                self.parent, "Error", "Cannot overwrite the running script file!"
            )
            return

        # Write header to the output file
        with atomic_write(
            output_path, mode="w", encoding="utf-8", overwrite=True
        ) as f:
            f.write(f"# Concatenated Files from: {working_dir}\n")
            f.write(
                f"# Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            )
            f.write(f"# Total directory size: {working_dir.name}\n")

            # Show selected file types in a readable format
            if len(selected_language_names) == len(selected_language_names):
                f.write("# Selected file types: All types\n")
            else:
                f.write(f"# Selected file types: {', '.join(selected_language_names)}\n")

            f.write("\n" + "=" * 60 + "\n")
            f.write("START OF CONCATENATED CONTENT\n")
            f.write("=" * 60 + "\n\n")
            f.flush()

            # Stream the content from the temporary file
            try:
                with open(temp_file_path, "r", encoding="utf-8") as temp_file:
                    shutil.copyfileobj(temp_file, f)

                f.write("\n" + "=" * 60 + "\n")
                f.write("END OF CONCATENATED CONTENT\n")
                f.write("=" * 60 + "\n")
            except Exception as e:
                error_msg = f"Error writing output file: {e}"
                logging.error(error_msg)
                raise IOError(error_msg)
            finally:
                # Clean up the temporary file
                try:
                    os.unlink(temp_file_path)
                except OSError as e:
                    logging.warning(
                        f"Could not remove temporary file {temp_file_path}: {e}"
                    )

        # Success message with file location
        QtWidgets.QMessageBox.information(
            self.parent,
            "Success",
            f"File generated successfully!\n\nSaved to:\n{output_filename}\n\nFile size: {output_path.stat().st_size:,} bytes",
        )
        logging.info(f"Successfully generated file: {output_filename}")