"""Background worker thread for file processing."""

import logging
import tempfile
import time
from pathlib import Path
from typing import List

from PyQt6 import QtCore

from source_stitcher.config import WorkerConfig
from source_stitcher.core.file_walker import ProjectFileWalker
from source_stitcher.core.language_loader import LanguageDefinitionLoader
from source_stitcher.core.file_reader import FileReader
from source_stitcher.core.output_builder import HeaderBuilder, ContentStreamer

logger = logging.getLogger(__name__)


class GeneratorWorker(QtCore.QObject):
    """
    Worker object to perform file discovery and processing in a separate thread.
    Uses unified file walker to eliminate double directory traversal.
    """

    discovery_progress = QtCore.pyqtSignal(str)  # "Scanning..." status
    pre_count_finished = QtCore.pyqtSignal(int)  # Total file count
    progress_updated = QtCore.pyqtSignal(int)  # Processing progress
    status_updated = QtCore.pyqtSignal(str)  # Status messages
    finished = QtCore.pyqtSignal(str, list, str)  # temp_path, processed_files, error

    def __init__(self, config: WorkerConfig) -> None:
        super().__init__()
        self.config = config
        self._is_cancelled = False

        # Initialize new components
        self.language_loader = LanguageDefinitionLoader(config.language_config_path)
        self.file_reader = FileReader(
            encodings=config.generation_options.encodings,
            default_encoding=config.generation_options.default_encoding,
        )

        logger.debug(f"Worker initialized with config: {self.config}")

    def cancel(self) -> None:
        """Signals the worker to stop processing."""
        self._is_cancelled = True
        logger.debug(f"Worker cancellation requested: {self._is_cancelled}")
        logger.info("Cancellation requested for worker.")

    @QtCore.pyqtSlot()
    def run(self) -> None:
        """Main execution method using streamlined single-pass architecture."""
        error_message = ""
        temp_path = ""
        processed_files: List[Path] = []

        logger.info(
            f"Worker starting processing of {len(self.config.generation_options.selected_paths)} items"
        )

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

            # Phase 2: Build header once before any file content is written
            logger.debug("Building header")
            header_builder = HeaderBuilder(
                self.config.generation_options.base_directory,
                file_list,
                self.config.selected_language_names,
            )
            header = header_builder.build()

            # Phase 3: Stream content directly to temp file in single pass
            self.status_updated.emit("Processing files...")
            logger.debug("Starting single-pass content streaming")
            processing_start_time = time.time()

            # Open temp file once and write everything in order
            with tempfile.NamedTemporaryFile(
                suffix=".md", delete=False, mode="w", encoding="utf-8"
            ) as fh:
                temp_path = fh.name
                
                # Write header first
                fh.write(header)
                fh.flush()

                # Stream file content directly
                content_streamer = ContentStreamer(self.file_reader, fh)
                files_processed_count, processed_files = content_streamer.stream_files(
                    file_list,
                    self.config.generation_options.base_directory,
                    lambda pct: self.progress_updated.emit(min(pct, 99)) if not self._is_cancelled else None,
                )

            processing_end_time = time.time()
            logger.debug(
                f"Processing phase finished in {processing_end_time - processing_start_time:.2f}s"
            )
            logger.info(
                f"Processing completed: {files_processed_count} files processed"
            )

            if self._is_cancelled:
                logger.info("Worker cancelled during processing phase.")
                if temp_path and Path(temp_path).exists():
                    Path(temp_path).unlink()
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
            if temp_path and Path(temp_path).exists():
                Path(temp_path).unlink()

            self.finished.emit("", [], error_message)

        finally:
            self.status_updated.emit("Finished")
