"""Dialog utilities for the Source Stitcher application."""

import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import List

from PyQt6 import QtCore, QtWidgets
from atomicwrites import atomic_write

from ..core.tree_generator import ProjectTreeGenerator

logger = logging.getLogger(__name__)


class SaveFileDialog:
    """Handles the save file dialog and file writing operations."""
    
    def __init__(self, parent_window):
        self.parent = parent_window
        logger.debug("SaveFileDialog initialized.")
    
    def save_generated_file(self, temp_file_path: str, working_dir: Path, selected_language_names: list, processed_files: list = None) -> None:
        """Handles the save file dialog and writing the output."""
        desktop_path = self._find_desktop_path()
        initial_filename = self._generate_filename(working_dir, selected_language_names)
        default_path = desktop_path / initial_filename
        logger.info(f"Save dialog defaulting to: {default_path}")

        logger.debug("Opening save file dialog.")
        file_dialog = QtWidgets.QFileDialog(
            self.parent, "Save Concatenated File", str(default_path),
            "Markdown Files (*.md);;Text Files (*.txt);;All Files (*)",
        )
        file_dialog.setFileMode(QtWidgets.QFileDialog.FileMode.AnyFile)
        file_dialog.setAcceptMode(QtWidgets.QFileDialog.AcceptMode.AcceptSave)
        file_dialog.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
        
        if file_dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            output_filename = file_dialog.selectedFiles()[0]
            logger.debug(f"File dialog accepted. Selected file: {output_filename}")
        else:
            output_filename = ""
            logger.info("Save operation cancelled by user.")

        if not output_filename:
            QtWidgets.QMessageBox.information(self.parent, "Cancelled", "Save operation cancelled.")
            return

        try:
            self._write_output_file(output_filename, temp_file_path, working_dir, selected_language_names, processed_files)
        except Exception as e:
            logger.error(f"Error writing output file {output_filename}: {e}", exc_info=True)
            QtWidgets.QMessageBox.critical(self.parent, "Error", f"Could not write output file:\n{output_filename}\n\n{e}")
    
    def _find_desktop_path(self) -> Path:
        """Find the desktop directory with fallbacks."""
        possible_desktop_paths = [
            Path.home() / "Desktop", Path.home() / "desktop", Path.home() / "Bureau",
            Path.home() / "Escritorio", Path.home() / "Área de Trabalho",
        ]
        for path in possible_desktop_paths:
            logger.debug(f"Checking for desktop path: {path}")
            if path.exists() and path.is_dir():
                logger.debug(f"Found desktop path: {path}")
                return path
        logger.info("Desktop directory not found, using home directory as default")
        return Path.home()
    
    def _generate_filename(self, working_dir: Path, selected_language_names: list) -> str:
        """Generate a filename based on directory and selected languages."""
        logger.debug("Generating filename.")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dir_name = working_dir.name if working_dir.name else "files"

        if len(selected_language_names) <= 2:
            lang_suffix = "_".join(selected_language_names)
        elif len(selected_language_names) <= 4:
            lang_suffix = "_".join(selected_language_names[:3]) + "_etc"
        else:
            lang_suffix = "mixed_types"
        lang_suffix = lang_suffix.replace("/", "_").replace("&", "and").replace(" ", "_")

        initial_filename = f"{dir_name}_{lang_suffix}_{timestamp}.md"
        if len(initial_filename) > 100:
            initial_filename = f"concatenated_{dir_name}_{timestamp}.md"
        
        logger.debug(f"Generated filename: {initial_filename}")
        return initial_filename
    
    def _extract_file_paths_from_temp(self, temp_file_path: str, working_dir: Path) -> List[Path]:
        """Extract file paths from the temporary file by parsing the file headers."""
        processed_files = []
        try:
            with open(temp_file_path, "r", encoding="utf-8") as temp_file:
                for line in temp_file:
                    line = line.strip()
                    if line.startswith("--- File: ") and line.endswith(" ---"):
                        # Extract the relative path from "--- File: path/to/file.ext ---"
                        rel_path_str = line[10:-4]  # Remove "--- File: " and " ---"
                        try:
                            full_path = working_dir / rel_path_str
                            if full_path.exists():
                                processed_files.append(full_path)
                        except Exception as e:
                            logger.warning(f"Could not process file path '{rel_path_str}': {e}")
                            continue
        except Exception as e:
            logger.error(f"Error extracting file paths from temporary file: {e}")
        
        logger.debug(f"Extracted {len(processed_files)} file paths from temporary file.")
        return processed_files
    
    def _write_output_file(self, output_filename: str, temp_file_path: str, working_dir: Path, selected_language_names: list, processed_files: list = None) -> None:
        """Write the final output file."""
        logger.debug(f"Writing output to file: {output_filename}")
        output_path = Path(output_filename)

        if "__file__" in globals() and output_path.resolve() == Path(__file__).resolve():
            QtWidgets.QMessageBox.critical(self.parent, "Error", "Cannot overwrite the running script file!")
            return

        with atomic_write(output_path, mode="w", encoding="utf-8", overwrite=True) as f:
            logger.debug("Writing file header.")
            f.write(f"# Concatenated Files from: {working_dir}\n")
            f.write(f"# Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"# Total directory size: {working_dir.name}\n")
            if len(selected_language_names) == len(self.parent.language_extensions):
                f.write("# Selected file types: All types\n")
            else:
                f.write(f"# Selected file types: {', '.join(selected_language_names)}\n")
            
            # Generate and write tree structure
            logger.debug("Generating tree structure from processed files list.")
            if processed_files:
                # Use passed processed files list (new optimized approach)
                files_to_use = processed_files
            else:
                # Fallback to extracting from temp file (legacy approach)
                logger.debug("No processed files list provided, extracting from temporary file.")
                files_to_use = self._extract_file_paths_from_temp(temp_file_path, working_dir)
            
            if files_to_use:
                tree_generator = ProjectTreeGenerator(working_dir)
                tree_content = tree_generator.generate_tree(files_to_use)
                
                f.write("\n# Selected Files\n\n")
                f.write("```\n")
                f.write(tree_content)
                f.write("\n```\n\n")
                f.flush()
            
            f.write("\n" + "=" * 60 + "\n")
            f.write("START OF CONCATENATED CONTENT\n")
            f.write("=" * 60 + "\n\n")
            f.flush()

            logger.debug(f"Streaming content from temporary file: {temp_file_path}")
            try:
                with open(temp_file_path, "r", encoding="utf-8") as temp_file:
                    shutil.copyfileobj(temp_file, f)
                f.write("\n" + "=" * 60 + "\n")
                f.write("END OF CONCATENATED CONTENT\n")
                f.write("=" * 60 + "\n")
            except Exception as e:
                error_msg = f"Error writing output file: {e}"
                logger.error(error_msg, exc_info=True)
                raise IOError(error_msg)
            finally:
                logger.debug(f"Removing temporary file: {temp_file_path}")
                try:
                    os.unlink(temp_file_path)
                except OSError as e:
                    logger.warning(f"Could not remove temporary file {temp_file_path}: {e}")

        logger.info(f"Successfully generated file: {output_filename}")
        QtWidgets.QMessageBox.information(
            self.parent, "Success",
            f"File generated successfully!\n\nSaved to:\n{output_filename}\n\nFile size: {output_path.stat().st_size:,} bytes",
        )