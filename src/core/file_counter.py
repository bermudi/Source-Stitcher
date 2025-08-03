"""File counting utilities for progress tracking."""

import logging
import os
import stat
import time
from pathlib import Path
from typing import Set, Tuple
import pathspec

from ..config import WorkerConfig
from ..file_utils import is_binary_file, matches_file_type

logger = logging.getLogger(__name__)


class FileCounter:
    """Handles counting files for progress tracking."""
    
    def __init__(self, config: WorkerConfig):
        self.config = config
        self._is_cancelled = False
    
    def cancel(self):
        """Signal cancellation."""
        self._is_cancelled = True
    
    def count_directory_recursive(
        self,
        dir_path: Path,
        current_dir_ignore_spec: pathspec.PathSpec | None,
        seen: Set[Tuple[int, int]],
    ) -> int:
        """
        Recursively count matching files in the directory, respecting filters and ignore patterns.
        """
        count = 0
        logger.info(f"File counting started for: {dir_path}")
        start_time = time.time()

        def walk_error_handler(error: OSError) -> None:
            logger.warning(
                f"Permission/OS error during count walk below {dir_path}: {error}"
            )

        for root, dirs, files in os.walk(
            dir_path, topdown=True, onerror=walk_error_handler, followlinks=False
        ):
            if self._is_cancelled:
                return count
            root_path = Path(root)
            logger.debug(f"Counting files in directory: {root_path}")

            dirs.sort(key=str.lower)
            files.sort(key=str.lower)

            try:
                root_relative_to_base = root_path.relative_to(
                    self.config.generation_options.base_directory
                )
                root_relative_to_current = root_path.relative_to(dir_path)
            except ValueError:
                logger.warning(
                    f"Count: Could not make path relative during walk: {root_path}. Skipping subtree."
                )
                dirs[:] = []
                continue

            original_dirs = list(dirs)
            filtered_dirs = []
            for d in original_dirs:
                is_ignored = False
                full_dir_path_str = str(root_relative_to_base / d) + "/"
                if d.startswith("."):
                    is_ignored = True
                    logger.debug(f"Directory {d} excluded (starts with '.')")
                elif self.config.filter_settings.ignore_spec and self.config.filter_settings.ignore_spec.match_file(full_dir_path_str):
                    is_ignored = True
                    logger.debug(f"Directory {d} excluded by project ignore patterns")
                elif current_dir_ignore_spec and current_dir_ignore_spec.match_file(str(root_relative_to_current / d) + "/"):
                    is_ignored = True
                    logger.debug(f"Directory {d} excluded by local ignore patterns")
                elif self.config.filter_settings.global_ignore_spec and self.config.filter_settings.global_ignore_spec.match_file(full_dir_path_str):
                    is_ignored = True
                    logger.debug(f"Directory {d} excluded by global ignore patterns")

                if not is_ignored:
                    filtered_dirs.append(d)
            dirs[:] = filtered_dirs


            for file_name in files:
                if self._is_cancelled:
                    return count

                full_path = root_path / file_name
                logger.debug(f"Evaluating file: {file_name}")

                if file_name.startswith("."):
                    logger.debug(f"File {file_name} excluded: starts with '.'")
                    continue

                try:
                    st = os.stat(full_path)
                    if not stat.S_ISREG(st.st_mode) or st.st_size == 0:
                        logger.debug(f"File {file_name} excluded: not a regular file or empty")
                        continue
                except OSError as e:
                    logger.warning(
                        f"Could not stat file during count walk: {full_path}, error: {e}. Skipping."
                    )
                    continue

                try:
                    relative_path_to_base = full_path.relative_to(
                        self.config.generation_options.base_directory
                    )
                    relative_path_to_current = full_path.relative_to(dir_path)
                except ValueError:
                    logger.warning(
                        f"Could not make file path relative during count walk: {full_path}. Skipping."
                    )
                    continue

                relative_path_str = str(relative_path_to_base)
                if self.config.filter_settings.ignore_spec and self.config.filter_settings.ignore_spec.match_file(relative_path_str):
                    logger.debug(f"File {file_name} excluded: matches project ignore spec")
                    continue

                if current_dir_ignore_spec and current_dir_ignore_spec.match_file(str(relative_path_to_current)):
                    logger.debug(f"File {file_name} excluded: matches local ignore spec")
                    continue

                if self.config.filter_settings.global_ignore_spec and self.config.filter_settings.global_ignore_spec.match_file(relative_path_str):
                    logger.debug(f"File {file_name} excluded: matches global ignore spec")
                    continue

                if not matches_file_type(
                    full_path,
                    self.config.filter_settings.selected_extensions,
                    self.config.filter_settings.selected_filenames,
                    self.config.filter_settings.all_known_extensions,
                    self.config.filter_settings.all_known_filenames,
                    self.config.filter_settings.handle_other_text_files,
                ):
                    logger.debug(f"File {file_name} excluded: does not match file type criteria")
                    continue

                if is_binary_file(full_path):
                    logger.debug(f"File {file_name} excluded: detected as binary")
                    continue

                dev_ino = (st.st_dev, st.st_ino)
                if dev_ino in seen:
                    logger.debug(f"File {file_name} excluded: duplicate file (same inode)")
                    continue
                seen.add(dev_ino)

                count += 1
                logger.debug(f"File {file_name} matches criteria, count: {count}")

        end_time = time.time()
        logger.info(f"Found {count} matching files in {dir_path}")
        logger.debug(f"Finished counting for {dir_path} in {end_time - start_time:.2f}s")
        return count