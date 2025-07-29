"""File processing logic for directory traversal and content extraction."""

import logging
import os
import stat
from pathlib import Path
from typing import List, Set, Tuple
import pathspec

from ..config import WorkerConfig
from ..file_utils import matches_file_type
from .file_reader import FileReader


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
    ) -> None:
        """
        Recursively process directory for files, appending to output_content.
        Updates files_processed_counter[0] for progress tracking.
        """
        if self._is_cancelled:
            return

        def walk_error_handler(error: OSError) -> None:
            logging.warning(
                f"Permission/OS error during processing walk below {dir_path}: {error}"
            )

        for root, dirs, files in os.walk(
            dir_path, topdown=True, onerror=walk_error_handler, followlinks=False
        ):
            if self._is_cancelled:
                return
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
                    f"Process: Could not make path relative during walk: {root_path}. Skipping subtree."
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
                    return
                if file_name.startswith("."):
                    continue

                full_path = root_path / file_name

                try:
                    st = os.stat(full_path)
                    if not stat.S_ISREG(st.st_mode) or st.st_size == 0:
                        continue
                except OSError as e:
                    logging.warning(
                        f"Could not stat file during process walk: {full_path}, error: {e}. Skipping."
                    )
                    continue

                dev_ino = (st.st_dev, st.st_ino)
                if dev_ino in seen:
                    logging.info(f"Skipping duplicate file (same inode): {full_path}")
                    continue
                seen.add(dev_ino)

                try:
                    relative_path_to_base = full_path.relative_to(
                        self.config.generation_options.base_directory
                    )
                    relative_path_to_current = full_path.relative_to(dir_path)
                except ValueError:
                    logging.warning(
                        f"Could not make file path relative during process walk: {full_path}. Skipping."
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

                try:
                    file_content = self.file_reader.get_file_content(full_path)
                    if file_content is None:
                        continue

                    relative_path_output = relative_path_to_base
                    ext = full_path.suffix[1:] if full_path.suffix else "txt"

                    # Write directly to the output file
                    output_file.write(f"\n--- File: {relative_path_output} ---\n")
                    output_file.write(f"```{ext}\n")
                    output_file.write(file_content)
                    output_file.write("\n```\n\n")
                    output_file.flush()  # Ensure content is written

                    files_processed_counter[0] += 1
                except IOError as e:
                    logging.error(f"Error writing file {full_path}: {e}")
                    continue