"""File processing logic for directory traversal and content extraction."""

import logging
import os
import stat
import time
from pathlib import Path
from typing import List, Optional, Set, Tuple
import pathspec

from ..config import WorkerConfig
from ..file_utils import matches_file_type
from .file_reader import FileReader

logger = logging.getLogger(__name__)


class FileProcessor:
    """Handles processing files and directories."""
    
    def __init__(self, config: WorkerConfig):
        self.config = config
        self.file_reader = FileReader(
            encodings=config.generation_options.encodings,
            default_encoding=config.generation_options.default_encoding
        )
        self._is_cancelled = False
    
    def cancel(self):
        """Signal cancellation."""
        self._is_cancelled = True

    def process_directory_recursive(
        self,
        dir_path: Path,
        current_dir_ignore_spec: pathspec.PathSpec | None,
        output_file,
        files_processed_counter: List[int],
        seen: Set[Tuple[int, int]],
        processed_files: Optional[List[Path]] = None,
    ) -> None:
        """
        Recursively process directory for files, appending to output_content.
        Updates files_processed_counter[0] for progress tracking.
        """
        if self._is_cancelled:
            return

        logger.debug(f"Starting directory traversal: {dir_path}")
        start_time = time.time()

        def walk_error_handler(error: OSError) -> None:
            logger.warning(
                f"Permission/OS error during processing walk below {dir_path}: {error}"
            )

        for root, dirs, files in os.walk(
            dir_path, topdown=True, onerror=walk_error_handler, followlinks=False
        ):
            if self._is_cancelled:
                return
            root_path = Path(root)

            logger.info(f"Processing directory: {root_path} ({len(files)} files)")

            dirs.sort(key=str.lower)
            files.sort(key=str.lower)

            try:
                root_relative_to_base = root_path.relative_to(
                    self.config.generation_options.base_directory
                )
                root_relative_to_current = root_path.relative_to(dir_path)
            except ValueError:
                logger.warning(
                    f"Process: Could not make path relative during walk: {root_path}. Skipping subtree."
                )
                dirs[:] = []
                continue

            original_dirs = list(dirs)

            # Directory filtering logic
            filtered_dirs = []
            for d in original_dirs:
                is_ignored = False
                if d.startswith("."):
                    is_ignored = True
                    logger.debug(f"Directory {d} ignored (starts with '.')")

                full_dir_path_str = str(root_relative_to_base / d) + "/"
                if not is_ignored and self.config.filter_settings.ignore_spec and self.config.filter_settings.ignore_spec.match_file(full_dir_path_str):
                    is_ignored = True
                    logger.debug(f"Directory {d} excluded by project ignore patterns")

                if not is_ignored and current_dir_ignore_spec and current_dir_ignore_spec.match_file(str(root_relative_to_current / d) + "/"):
                    is_ignored = True
                    logger.debug(f"Directory {d} excluded by local ignore patterns")

                if not is_ignored and self.config.filter_settings.global_ignore_spec and self.config.filter_settings.global_ignore_spec.match_file(full_dir_path_str):
                    is_ignored = True
                    logger.debug(f"Directory {d} excluded by global ignore patterns")

                if not is_ignored:
                    filtered_dirs.append(d)

            dirs[:] = filtered_dirs

            for file_name in files:
                if self._is_cancelled:
                    return

                full_path = root_path / file_name
                logger.debug(f"Applying filters to file: {full_path}")

                if file_name.startswith("."):
                    logger.debug(f"File {file_name} ignored (starts with '.')")
                    continue

                try:
                    st = os.stat(full_path)
                    if not stat.S_ISREG(st.st_mode) or st.st_size == 0:
                        logger.debug(f"File {file_name} ignored (not a regular file or empty)")
                        continue
                except OSError as e:
                    logger.warning(
                        f"Could not stat file during process walk: {full_path}, error: {e}. Skipping."
                    )
                    continue

                dev_ino = (st.st_dev, st.st_ino)
                if dev_ino in seen:
                    logger.info(f"Skipping duplicate file (same inode): {full_path}")
                    continue
                seen.add(dev_ino)

                try:
                    relative_path_to_base = full_path.relative_to(
                        self.config.generation_options.base_directory
                    )
                    relative_path_to_current = full_path.relative_to(dir_path)
                except ValueError:
                    logger.warning(
                        f"Could not make file path relative during process walk: {full_path}. Skipping."
                    )
                    continue

                relative_path_str = str(relative_path_to_base)
                if self.config.filter_settings.ignore_spec and self.config.filter_settings.ignore_spec.match_file(relative_path_str):
                    logger.debug(f"File {file_name} ignored by project ignore spec")
                    continue

                if current_dir_ignore_spec and current_dir_ignore_spec.match_file(str(relative_path_to_current)):
                    logger.debug(f"File {file_name} ignored by local ignore spec")
                    continue

                if self.config.filter_settings.global_ignore_spec and self.config.filter_settings.global_ignore_spec.match_file(relative_path_str):
                    logger.debug(f"File {file_name} ignored by global ignore spec")
                    continue

                if not matches_file_type(
                    full_path,
                    self.config.filter_settings.selected_extensions,
                    self.config.filter_settings.selected_filenames,
                    self.config.filter_settings.all_known_extensions,
                    self.config.filter_settings.all_known_filenames,
                    self.config.filter_settings.handle_other_text_files,
                ):
                    logger.debug(f"File {file_name} failed to match file type criteria")
                    continue

                logger.debug(f"File {file_name} passed all filters")

                try:
                    file_content = self.file_reader.get_file_content(full_path)
                    if file_content is None:
                        continue

                    # Track processed file if list provided
                    if processed_files is not None:
                        processed_files.append(full_path)

                    relative_path_output = relative_path_to_base
                    ext = full_path.suffix[1:] if full_path.suffix else "txt"

                    logger.debug(f"Writing file content: {relative_path_output}")
                    output_file.write(f"\n--- File: {relative_path_output} ---\n")
                    output_file.write(f"```{ext}\n")
                    output_file.write(file_content)
                    output_file.write("\n```\n\n")
                    output_file.flush()

                    files_processed_counter[0] += 1
                    logger.info(f"Processed {files_processed_counter[0]} files so far")

                except IOError as e:
                    logger.error(f"Error writing file {full_path}: {e}")
                    continue

        end_time = time.time()
        logger.debug(f"Finished directory traversal for {dir_path} in {end_time - start_time:.2f}s")