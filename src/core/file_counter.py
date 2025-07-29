"""File counting utilities for progress tracking."""

import logging
import os
import stat
from pathlib import Path
from typing import Set, Tuple
import pathspec

from ..config import WorkerConfig
from ..file_utils import is_binary_file, matches_file_type


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

        def walk_error_handler(error: OSError) -> None:
            logging.warning(
                f"Permission/OS error during count walk below {dir_path}: {error}"
            )

        for root, dirs, files in os.walk(
            dir_path, topdown=True, onerror=walk_error_handler, followlinks=False
        ):
            if self._is_cancelled:
                return count
            root_path = Path(root)

            dirs.sort(key=str.lower)
            files.sort(key=str.lower)

            try:
                root_relative_to_base = root_path.relative_to(
                    self.config.generation_options.base_directory
                )
                root_relative_to_current = root_path.relative_to(dir_path)
            except ValueError:
                logging.warning(
                    f"Count: Could not make path relative during walk: {root_path}. Skipping subtree."
                )
                dirs[:] = []
                continue

            original_dirs = list(dirs)
            dirs[:] = [
                d
                for d in original_dirs
                if not d.startswith(".")
                and (
                    not self.config.filter_settings.ignore_spec
                    or not self.config.filter_settings.ignore_spec.match_file(
                        str(root_relative_to_base / d) + "/"
                    )
                )
                and (
                    not current_dir_ignore_spec
                    or not current_dir_ignore_spec.match_file(
                        str(root_relative_to_current / d) + "/"
                    )
                )
                and (
                    not self.config.filter_settings.global_ignore_spec
                    or not self.config.filter_settings.global_ignore_spec.match_file(
                        str(root_relative_to_base / d) + "/"
                    )
                )
            ]

            for file_name in files:
                if self._is_cancelled:
                    return count
                if file_name.startswith("."):
                    continue

                full_path = root_path / file_name

                try:
                    st = os.stat(full_path)
                    if not stat.S_ISREG(st.st_mode) or st.st_size == 0:
                        continue
                except OSError as e:
                    logging.warning(
                        f"Could not stat file during count walk: {full_path}, error: {e}. Skipping."
                    )
                    continue

                try:
                    relative_path_to_base = full_path.relative_to(
                        self.config.generation_options.base_directory
                    )
                    relative_path_to_current = full_path.relative_to(dir_path)
                except ValueError:
                    logging.warning(
                        f"Could not make file path relative during count walk: {full_path}. Skipping."
                    )
                    continue

                if (
                    (
                        self.config.filter_settings.ignore_spec
                        and self.config.filter_settings.ignore_spec.match_file(
                            str(relative_path_to_base)
                        )
                    )
                    or (
                        current_dir_ignore_spec
                        and current_dir_ignore_spec.match_file(
                            str(relative_path_to_current)
                        )
                    )
                    or (
                        self.config.filter_settings.global_ignore_spec
                        and self.config.filter_settings.global_ignore_spec.match_file(
                            str(relative_path_to_base)
                        )
                    )
                ):
                    continue

                # Use the new matching logic
                if not matches_file_type(
                    full_path,
                    self.config.filter_settings.selected_extensions,
                    self.config.filter_settings.selected_filenames,
                    self.config.filter_settings.all_known_extensions,
                    self.config.filter_settings.all_known_filenames,
                    self.config.filter_settings.handle_other_text_files,
                ):
                    continue

                if is_binary_file(full_path):
                    continue

                dev_ino = (st.st_dev, st.st_ino)
                if dev_ino in seen:
                    continue
                seen.add(dev_ino)
                count += 1

        return count