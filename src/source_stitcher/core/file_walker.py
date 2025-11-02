"""Unified file discovery and filtering for Source-Stitcher."""

import logging
import os
import stat
import time
from pathlib import Path
from typing import List, Set, Tuple, Optional
import pathspec

from ..config import WorkerConfig
from ..file_utils import is_binary_file, load_ignore_patterns, matches_file_type

logger = logging.getLogger(__name__)


class ProjectFileWalker:
    """
    Unified file walker that handles both discovery and filtering in a single pass.
    Eliminates the duplicate logic between FileCounter and FileProcessor.
    """

    def __init__(
        self, config: WorkerConfig, progress_callback: Optional[callable] = None
    ):
        """
        Initialize the file walker with configuration.

        Args:
            config: Worker configuration containing filter settings and generation options
            progress_callback: Optional callback for progress updates during discovery
        """
        self.config = config
        self.progress_callback = progress_callback
        self._is_cancelled = False
        logger.debug(f"ProjectFileWalker initialized with config: {config}")

    def cancel(self) -> None:
        """Signal cancellation of the file discovery process."""
        self._is_cancelled = True
        logger.debug("ProjectFileWalker cancellation requested")

    def discover_files(self) -> Tuple[List[Path], int]:
        """
        Discovery phase - collect all matching files in a single directory traversal.

        Returns:
            Tuple of (file_list, total_count) where:
            - file_list: List of Path objects for all matching files
            - total_count: Total number of files found
        """
        logger.info("Starting unified file discovery phase")
        start_time = time.time()

        discovered_files: List[Path] = []
        seen: Set[Tuple[int, int]] = set()

        # Sort paths for consistent processing order
        self.config.generation_options.selected_paths.sort(key=lambda p: p.name.lower())

        for path in self.config.generation_options.selected_paths:
            if self._is_cancelled:
                logger.info("File discovery cancelled")
                break

            if self.progress_callback:
                self.progress_callback(f"Scanning {path.name}...")

            logger.debug(f"Discovering files in: {path}")

            try:
                st = os.stat(path)
                is_regular_file = stat.S_ISREG(st.st_mode)
                is_regular_dir = stat.S_ISDIR(st.st_mode)

                if is_regular_file:
                    if self._should_include_file(path, st, seen):
                        discovered_files.append(path)
                        seen.add((st.st_dev, st.st_ino))
                        logger.debug(f"Added file: {path}")

                elif is_regular_dir:
                    if not self._is_directory_ignored(path):
                        current_dir_ignore_spec = load_ignore_patterns(
                            path,
                            use_gitignore=self.config.filter_settings.use_gitignore,
                            use_npmignore=self.config.filter_settings.use_npmignore,
                            use_dockerignore=self.config.filter_settings.use_dockerignore,
                        )
                        dir_files = self._discover_directory_recursive(
                            path, current_dir_ignore_spec, seen
                        )
                        discovered_files.extend(dir_files)
                        logger.debug(
                            f"Added {len(dir_files)} files from directory: {path}"
                        )

            except (OSError, ValueError) as e:
                logger.error(f"Error discovering files in {path}: {e}")
                continue
            except Exception as e:
                logger.error(
                    f"Unexpected error discovering files in {path}: {e}", exc_info=True
                )
                continue

        end_time = time.time()
        total_count = len(discovered_files)
        logger.info(
            f"File discovery completed: {total_count} files found in {end_time - start_time:.2f}s"
        )

        return discovered_files, total_count

    def _discover_directory_recursive(
        self,
        dir_path: Path,
        current_dir_ignore_spec: Optional[pathspec.PathSpec],
        seen: Set[Tuple[int, int]],
    ) -> List[Path]:
        """
        Recursively discover files in a directory, applying all filtering logic.

        Args:
            dir_path: Directory to scan
            current_dir_ignore_spec: Local ignore patterns for this directory
            seen: Set of (dev, ino) tuples to avoid duplicate files

        Returns:
            List of Path objects for matching files in the directory
        """
        discovered_files: List[Path] = []

        def walk_error_handler(error: OSError) -> None:
            logger.warning(
                f"Permission/OS error during discovery walk below {dir_path}: {error}"
            )

        for root, dirs, files in os.walk(
            dir_path, topdown=True, onerror=walk_error_handler, followlinks=False
        ):
            if self._is_cancelled:
                break

            root_path = Path(root)
            logger.debug(f"Discovering files in directory: {root_path}")

            # Sort for consistent processing order
            dirs.sort(key=str.lower)
            files.sort(key=str.lower)

            try:
                root_relative_to_base = root_path.relative_to(
                    self.config.generation_options.base_directory
                )
                root_relative_to_current = root_path.relative_to(dir_path)
            except ValueError:
                logger.warning(
                    f"Could not make path relative during discovery: {root_path}. Skipping subtree."
                )
                dirs[:] = []
                continue

            # Filter directories in-place
            self._filter_directories(
                dirs,
                root_relative_to_base,
                root_relative_to_current,
                current_dir_ignore_spec,
            )

            # Process files in current directory
            for file_name in files:
                if self._is_cancelled:
                    break

                full_path = root_path / file_name

                try:
                    st = os.stat(full_path)
                    if self._should_include_file(
                        full_path,
                        st,
                        seen,
                        current_dir_ignore_spec,
                        root_relative_to_current,
                    ):
                        discovered_files.append(full_path)
                        seen.add((st.st_dev, st.st_ino))
                        logger.debug(f"Discovered file: {full_path}")
                except (OSError, ValueError) as e:
                    logger.warning(
                        f"Could not process file during discovery: {full_path}, error: {e}"
                    )
                    continue

        return discovered_files

    def _filter_directories(
        self,
        dirs: List[str],
        root_relative_to_base: Path,
        root_relative_to_current: Path,
        current_dir_ignore_spec: Optional[pathspec.PathSpec],
    ) -> None:
        """
        Filter directories in-place, removing ignored directories from the list.

        Args:
            dirs: List of directory names to filter (modified in-place)
            root_relative_to_base: Current root path relative to base directory
            root_relative_to_current: Current root path relative to current directory
            current_dir_ignore_spec: Local ignore patterns
        """
        original_dirs = list(dirs)
        dirs.clear()

        for d in original_dirs:
            if self._is_directory_ignored_by_name(
                d,
                root_relative_to_base,
                root_relative_to_current,
                current_dir_ignore_spec,
            ):
                logger.debug(f"Directory {d} ignored by filters")
                continue
            dirs.append(d)

    def _is_directory_ignored(self, dir_path: Path) -> bool:
        """
        Check if a top-level directory should be ignored.

        Args:
            dir_path: Directory path to check

        Returns:
            True if directory should be ignored
        """
        try:
            rel_path_str = (
                str(dir_path.relative_to(self.config.generation_options.base_directory))
                + "/"
            )
        except ValueError:
            return False

        # Check project ignore patterns
        if (
            self.config.filter_settings.ignore_spec
            and self.config.filter_settings.ignore_spec.match_file(rel_path_str)
        ):
            return True

        # Check global ignore patterns
        if (
            self.config.filter_settings.global_ignore_spec
            and self.config.filter_settings.global_ignore_spec.match_file(rel_path_str)
        ):
            return True

        return False

    def _is_directory_ignored_by_name(
        self,
        dir_name: str,
        root_relative_to_base: Path,
        root_relative_to_current: Path,
        current_dir_ignore_spec: Optional[pathspec.PathSpec],
    ) -> bool:
        """
        Check if a directory should be ignored based on various ignore patterns.

        Args:
            dir_name: Name of the directory
            root_relative_to_base: Current root path relative to base directory
            root_relative_to_current: Current root path relative to current directory
            current_dir_ignore_spec: Local ignore patterns

        Returns:
            True if directory should be ignored
        """
        # Skip hidden directories
        if dir_name.startswith("."):
            return True

        full_dir_path_str = str(root_relative_to_base / dir_name) + "/"

        # Check project ignore patterns
        if (
            self.config.filter_settings.ignore_spec
            and self.config.filter_settings.ignore_spec.match_file(full_dir_path_str)
        ):
            return True

        # Check local ignore patterns
        if current_dir_ignore_spec and current_dir_ignore_spec.match_file(
            str(root_relative_to_current / dir_name) + "/"
        ):
            return True

        # Check global ignore patterns
        if (
            self.config.filter_settings.global_ignore_spec
            and self.config.filter_settings.global_ignore_spec.match_file(
                full_dir_path_str
            )
        ):
            return True

        return False

    def _should_include_file(
        self,
        file_path: Path,
        st: os.stat_result,
        seen: Set[Tuple[int, int]],
        current_dir_ignore_spec: Optional[pathspec.PathSpec] = None,
        root_relative_to_current: Optional[Path] = None,
    ) -> bool:
        """
        Determine if a file should be included based on all filtering criteria.

        Args:
            file_path: Path to the file
            st: File stat result
            seen: Set of (dev, ino) tuples to avoid duplicates
            current_dir_ignore_spec: Local ignore patterns (for directory traversal)
            root_relative_to_current: Root path relative to current directory (for directory traversal)

        Returns:
            True if file should be included
        """
        # Skip non-regular files and empty files
        if not stat.S_ISREG(st.st_mode) or st.st_size == 0:
            return False

        # Skip hidden files
        if file_path.name.startswith("."):
            return False

        # Check for duplicate files (same inode)
        dev_ino = (st.st_dev, st.st_ino)
        if dev_ino in seen:
            return False

        try:
            relative_path_to_base = file_path.relative_to(
                self.config.generation_options.base_directory
            )
        except ValueError:
            logger.warning(f"Could not make file path relative: {file_path}")
            return False

        relative_path_str = str(relative_path_to_base)

        # Check project ignore patterns
        if (
            self.config.filter_settings.ignore_spec
            and self.config.filter_settings.ignore_spec.match_file(relative_path_str)
        ):
            return False

        # Check local ignore patterns (only during directory traversal)
        if current_dir_ignore_spec and root_relative_to_current is not None:
            try:
                relative_path_to_current = file_path.relative_to(
                    self.config.generation_options.base_directory
                    / root_relative_to_current
                )
                if current_dir_ignore_spec.match_file(str(relative_path_to_current)):
                    return False
            except ValueError:
                pass

        # Check global ignore patterns
        if (
            self.config.filter_settings.global_ignore_spec
            and self.config.filter_settings.global_ignore_spec.match_file(
                relative_path_str
            )
        ):
            return False

        # Check file type matching
        if not matches_file_type(
            file_path,
            self.config.filter_settings.selected_extensions,
            self.config.filter_settings.selected_filenames,
            self.config.filter_settings.all_known_extensions,
            self.config.filter_settings.all_known_filenames,
            self.config.filter_settings.handle_other_text_files,
        ):
            return False

        # Check if file is binary
        if is_binary_file(file_path):
            return False

        return True
