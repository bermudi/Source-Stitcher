"""Background worker thread for file processing."""

import logging
import os
import stat
import tempfile
from pathlib import Path
from typing import Set, Tuple

from PyQt6 import QtCore

from .config import WorkerConfig
from .core.file_counter import FileCounter
from .core.file_processor import FileProcessor
from .file_utils import is_binary_file, load_ignore_patterns, matches_file_type


class GeneratorWorker(QtCore.QObject):
    """
    Worker object to perform file counting and concatenation in a separate thread.
    """

    pre_count_finished = QtCore.pyqtSignal(int)
    progress_updated = QtCore.pyqtSignal(int)
    status_updated = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(str, str)

    def __init__(self, config: WorkerConfig) -> None:
        super().__init__()
        self.config = config
        self._is_cancelled = False
        self.file_counter = FileCounter(config)
        self.file_processor = FileProcessor(config)

    def cancel(self) -> None:
        """Signals the worker to stop processing."""
        self._is_cancelled = True
        self.file_counter.cancel()
        self.file_processor.cancel()
        logging.info("Cancellation requested for worker.")

    @QtCore.pyqtSlot()
    def run(self) -> None:
        """Main execution method for the worker thread."""
        error_message = ""

        # Pre-scan phase to count matching files accurately
        self.status_updated.emit("Pre-scanning files...")
        total_files = 0
        seen: Set[Tuple[int, int]] = set()
        self.config.generation_options.selected_paths.sort(key=lambda p: p.name.lower())
        
        for path in self.config.generation_options.selected_paths:
            if self._is_cancelled:
                break
            try:
                st = os.stat(path)
                is_regular_file = stat.S_ISREG(st.st_mode)
                is_regular_dir = stat.S_ISDIR(st.st_mode)

                rel_path_base_str = ""
                try:
                    rel_path_base_str = str(
                        path.relative_to(self.config.generation_options.base_directory)
                    )
                except ValueError:
                    pass

                if is_regular_file:
                    if st.st_size == 0:
                        continue
                    if (
                        self.config.filter_settings.ignore_spec
                        and self.config.filter_settings.ignore_spec.match_file(
                            rel_path_base_str
                        )
                    ):
                        continue
                    if (
                        self.config.filter_settings.global_ignore_spec
                        and self.config.filter_settings.global_ignore_spec.match_file(
                            rel_path_base_str
                        )
                    ):
                        continue

                    if not matches_file_type(
                        path,
                        self.config.filter_settings.selected_extensions,
                        self.config.filter_settings.selected_filenames,
                        self.config.filter_settings.all_known_extensions,
                        self.config.filter_settings.all_known_filenames,
                        self.config.filter_settings.handle_other_text_files,
                    ):
                        continue

                    if is_binary_file(path):
                        continue

                    dev_ino = (st.st_dev, st.st_ino)
                    if dev_ino in seen:
                        continue
                    seen.add(dev_ino)
                    total_files += 1

                elif is_regular_dir:
                    if (
                        self.config.filter_settings.ignore_spec
                        and self.config.filter_settings.ignore_spec.match_file(
                            rel_path_base_str + "/"
                        )
                    ):
                        continue
                    if (
                        self.config.filter_settings.global_ignore_spec
                        and self.config.filter_settings.global_ignore_spec.match_file(
                            rel_path_base_str + "/"
                        )
                    ):
                        continue

                    current_dir_ignore_spec = load_ignore_patterns(path)
                    total_files += self.file_counter.count_directory_recursive(
                        path,
                        current_dir_ignore_spec,
                        seen,
                    )

            except (OSError, ValueError) as e:
                logging.error(f"Worker: Error counting item {path.name}: {e}")
                continue
            except Exception as e:
                logging.error(
                    f"Worker: Unexpected error counting item {path.name}: {e}",
                    exc_info=True,
                )
                continue

        if self._is_cancelled:
            logging.info("Worker cancelled during pre-scan phase.")
            self.finished.emit("", "Operation cancelled.")
            return

        if total_files == 0:
            self.finished.emit("", "No matching files found.")
            return

        self.pre_count_finished.emit(total_files)
        self.status_updated.emit("Processing...")

        # Processing phase
        files_processed_count = 0

        # Create a temporary file for streaming output
        temp_fd, temp_path = tempfile.mkstemp(suffix=".md", text=True)
        output_file = os.fdopen(temp_fd, "w", encoding="utf-8")

        # Reset seen for processing
        seen = set()
        self.config.generation_options.selected_paths.sort(key=lambda p: p.name.lower())

        try:
            for path in self.config.generation_options.selected_paths:
                if self._is_cancelled:
                    break

                try:
                    st = os.stat(path)
                    is_regular_file = stat.S_ISREG(st.st_mode)
                    is_regular_dir = stat.S_ISDIR(st.st_mode)

                    rel_path_base_str = ""
                    try:
                        rel_path_base_str = str(
                            path.relative_to(
                                self.config.generation_options.base_directory
                            )
                        )
                    except ValueError:
                        pass

                    if is_regular_file:
                        if (
                            self.config.filter_settings.ignore_spec
                            and self.config.filter_settings.ignore_spec.match_file(
                                rel_path_base_str
                            )
                        ):
                            continue
                        if (
                            self.config.filter_settings.global_ignore_spec
                            and self.config.filter_settings.global_ignore_spec.match_file(
                                rel_path_base_str
                            )
                        ):
                            continue

                        dev_ino = (st.st_dev, st.st_ino)
                        if dev_ino in seen:
                            logging.info(
                                f"Skipping duplicate file (same inode): {path}"
                            )
                            continue
                        seen.add(dev_ino)

                        if matches_file_type(
                            path,
                            self.config.filter_settings.selected_extensions,
                            self.config.filter_settings.selected_filenames,
                            self.config.filter_settings.all_known_extensions,
                            self.config.filter_settings.all_known_filenames,
                            self.config.filter_settings.handle_other_text_files,
                        ):
                            file_content = self.file_processor.file_reader.get_file_content(path)
                            if file_content is not None:
                                ext = path.suffix[1:] if path.suffix else "txt"
                                try:
                                    output_file.write(
                                        f"\n--- File: {rel_path_base_str} ---\n"
                                    )
                                    output_file.write(f"```{ext}\n")
                                    output_file.write(file_content)
                                    output_file.write("\n```\n\n")
                                    output_file.flush()  # Ensure content is written
                                except IOError as e:
                                    error_message = f"Error writing to output file: {e}"
                                    logging.error(error_message)
                                    self.finished.emit("", error_message)
                                    output_file.close()
                                    os.unlink(temp_path)
                                    return
                                files_processed_count += 1
                                if total_files > 0:
                                    progress = int(
                                        (files_processed_count / total_files) * 100
                                    )
                                    self.progress_updated.emit(
                                        min(progress, 99)
                                    )  # Keep it below 100 until the end

                    elif is_regular_dir:
                        if (
                            self.config.filter_settings.ignore_spec
                            and self.config.filter_settings.ignore_spec.match_file(
                                rel_path_base_str + "/"
                            )
                        ):
                            continue
                        if (
                            self.config.filter_settings.global_ignore_spec
                            and self.config.filter_settings.global_ignore_spec.match_file(
                                rel_path_base_str + "/"
                            )
                        ):
                            continue

                        current_dir_ignore_spec = load_ignore_patterns(path)
                        # We pass a list to process_directory_recursive so it can be mutated
                        processed_counter_ref = [files_processed_count]
                        self.file_processor.process_directory_recursive(
                            path,
                            current_dir_ignore_spec,
                            output_file,  # Pass the file object instead of the list
                            processed_counter_ref,
                            seen,
                        )

                        # Update progress based on the mutated counter
                        newly_processed = (
                            processed_counter_ref[0] - files_processed_count
                        )
                        if newly_processed > 0:
                            files_processed_count = processed_counter_ref[0]
                            if total_files > 0:
                                progress = int(
                                    (files_processed_count / total_files) * 100
                                )
                                self.progress_updated.emit(min(progress, 99))

                except (OSError, ValueError) as e:
                    logging.error(f"Worker: Error processing item {path.name}: {e}")
                    continue
                except Exception as e:
                    logging.error(
                        f"Worker: Unexpected error processing item {path.name}: {e}",
                        exc_info=True,
                    )
                    error_message = f"Unexpected error during processing: {e}"
                    continue

            if self._is_cancelled:
                logging.info("Worker cancelled during processing phase.")
                self.finished.emit("", "Operation cancelled.")
                return

            if not error_message:
                self.progress_updated.emit(100)

            logging.info(
                f"Worker finished processing. Total files included: {files_processed_count}"
            )
            output_file.close()

            if not self._is_cancelled and not error_message:
                self.finished.emit(temp_path, "")
            else:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                if not error_message:  # If we got here and no error but cancelled
                    self.finished.emit("", "Operation cancelled.")
        except Exception as e:
            logging.error(f"Worker error: {e}", exc_info=True)
            error_message = f"Error during processing: {e}"
            if "output_file" in locals() and not output_file.closed:
                output_file.close()
            if "temp_path" in locals() and os.path.exists(temp_path):
                os.unlink(temp_path)
            self.finished.emit("", error_message)
        finally:
            self.status_updated.emit("Finished")