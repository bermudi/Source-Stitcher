"""Background worker thread for file processing."""

import logging
import os
import tempfile
import time
from pathlib import Path
from typing import List

from PyQt6 import QtCore

from .config import WorkerConfig
from .core.file_walker import ProjectFileWalker
from .core.language_loader import LanguageDefinitionLoader
from .core.file_reader import FileReader
from .core.tree_generator import ProjectTreeGenerator

logger = logging.getLogger(__name__)


class GeneratorWorker(QtCore.QObject):
    """
    Worker object to perform file discovery and processing in a separate thread.
    Uses unified file walker to eliminate double directory traversal.
    """

    discovery_progress = QtCore.pyqtSignal(str)  # "Scanning..." status
    pre_count_finished = QtCore.pyqtSignal(int)  # Total file count
    progress_updated = QtCore.pyqtSignal(int)    # Processing progress
    status_updated = QtCore.pyqtSignal(str)      # Status messages
    finished = QtCore.pyqtSignal(str, list, str) # temp_path, processed_files, error

    def __init__(self, config: WorkerConfig) -> None:
        super().__init__()
        self.config = config
        self._is_cancelled = False
        
        # Initialize new components
        self.language_loader = LanguageDefinitionLoader(config.language_config_path)
        self.file_reader = FileReader(
            encodings=config.generation_options.encodings,
            default_encoding=config.generation_options.default_encoding
        )
        
        logger.debug(f"Worker initialized with config: {self.config}")

    def cancel(self) -> None:
        """Signals the worker to stop processing."""
        self._is_cancelled = True
        logger.debug(f"Worker cancellation requested: {self._is_cancelled}")
        logger.info("Cancellation requested for worker.")

    @QtCore.pyqtSlot()
    def run(self) -> None:
        """Main execution method using unified file walker architecture."""
        error_message = ""
        temp_path = ""
        processed_files: List[Path] = []
        
        logger.info(f"Worker starting processing of {len(self.config.generation_options.selected_paths)} items")

        try:
            # Phase 1: Discovery - Single directory traversal to find all matching files
            self.status_updated.emit("Scanning files...")
            logger.debug("Starting unified discovery phase")
            
            def progress_callback(message: str):
                self.discovery_progress.emit(message)
            
            file_walker = ProjectFileWalker(self.config, progress_callback)
            file_list, total_count = file_walker.discover_files()
            
            if self._is_cancelled:
                logger.info("Worker cancelled during discovery phase.")
                self.finished.emit("", [], "Operation cancelled.")
                return

            if total_count == 0:
                logger.info("No matching files found.")
                self.finished.emit("", [], "No matching files found.")
                return

            logger.info(f"Discovery completed: {total_count} files found")
            self.pre_count_finished.emit(total_count)

            # Phase 2: Processing - Process files from the discovered list
            self.status_updated.emit("Processing files...")
            logger.debug("Starting processing phase")
            processing_start_time = time.time()
            
            temp_fd, temp_path = tempfile.mkstemp(suffix=".md", text=True)
            
            with os.fdopen(temp_fd, "w", encoding="utf-8") as output_file:
                # Write initial header
                output_file.write(f"# Selected Files\n\n")
                output_file.write("```\n")
                output_file.write(f"Processing {total_count} files...\n")
                output_file.write("```\n\n")
                output_file.flush()

                files_processed_count = 0
                
                for file_path in file_list:
                    if self._is_cancelled:
                        break
                    
                    try:
                        # Read file content
                        file_content = self.file_reader.get_file_content(file_path)
                        if file_content is not None:
                            processed_files.append(file_path)
                            
                            # Write file content to output
                            try:
                                rel_path = file_path.relative_to(self.config.generation_options.base_directory)
                                ext = file_path.suffix[1:] if file_path.suffix else "txt"
                                
                                output_file.write(f"\n--- File: {rel_path} ---\n")
                                output_file.write(f"```{ext}\n")
                                output_file.write(file_content)
                                output_file.write("\n```\n\n")
                                output_file.flush()
                                
                            except (ValueError, IOError) as e:
                                logger.error(f"Error writing file content for {file_path}: {e}")
                                continue
                            
                            files_processed_count += 1
                            
                            # Update progress
                            if total_count > 0:
                                progress = int((files_processed_count / total_count) * 100)
                                self.progress_updated.emit(min(progress, 99))
                                
                    except Exception as e:
                        logger.error(f"Error processing file {file_path}: {e}")
                        continue

                # Rewrite file with final content (remove initial header)
                output_file.seek(0)
                output_file.truncate()
                
                for file_path in processed_files:
                    try:
                        rel_path = file_path.relative_to(self.config.generation_options.base_directory)
                        file_content = self.file_reader.get_file_content(file_path)
                        if file_content is not None:
                            ext = file_path.suffix[1:] if file_path.suffix else "txt"
                            output_file.write(f"\n--- File: {rel_path} ---\n")
                            output_file.write(f"```{ext}\n")
                            output_file.write(file_content)
                            output_file.write("\n```\n\n")
                    except Exception as e:
                        logger.error(f"Error rewriting file content for {file_path}: {e}")
                        continue

            processing_end_time = time.time()
            logger.debug(f"Processing phase finished in {processing_end_time - processing_start_time:.2f}s")
            logger.info(f"Processing completed: {files_processed_count} files processed")

            if self._is_cancelled:
                logger.info("Worker cancelled during processing phase.")
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                self.finished.emit("", [], "Operation cancelled.")
                return

            if not error_message:
                self.progress_updated.emit(100)

            # Emit success with processed file list
            self.finished.emit(temp_path, processed_files, "")

        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)
            error_message = f"Error during processing: {e}"
            
            # Clean up temp file on error
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
            
            self.finished.emit("", [], error_message)
            
        finally:
            self.status_updated.emit("Finished")