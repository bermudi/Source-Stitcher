import sys
import os
import logging
import shutil
from pathlib import Path
from datetime import datetime
import pathspec
import stat
import traceback
from dataclasses import dataclass
from typing import Optional, Dict, List, Set, Tuple
from atomicwrites import atomic_write  # type: ignore
import subprocess

# PyQt6 imports
from PyQt6 import QtCore, QtWidgets, QtGui

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


# --- Configuration Dataclasses ---
@dataclass
class AppSettings:
    """Application-level settings and configuration."""

    window_title: str = "SOTA Concatenator"
    organization_name: str = "YourOrg"
    application_version: str = "1.5-tree"
    default_window_width: int = 700
    default_window_height: int = 650
    chunk_size_bytes: int = 1024
    memory_chunk_size_mb: int = 1


@dataclass
class FilterSettings:
    """File filtering and selection configuration."""

    selected_extensions: Set[str]
    selected_filenames: Set[str]
    all_known_extensions: Set[str]
    all_known_filenames: Set[str]
    handle_other_text_files: bool
    ignore_spec: Optional[pathspec.PathSpec] = None
    global_ignore_spec: Optional[pathspec.PathSpec] = None
    search_text: str = ""


@dataclass
class GenerationOptions:
    """Options for file generation and processing."""

    selected_paths: List[Path]
    base_directory: Path
    output_format: str = "markdown"
    include_file_stats: bool = True
    include_timestamp: bool = True
    max_file_size_mb: int = 100
    # List of encodings to try in order, with fallbacks
    encodings: List[str] = None
    # Default encoding to use if none specified
    default_encoding: str = "utf-8"
    line_ending: str = "\n"

    def __post_init__(self):
        # Set default encodings if not provided
        if self.encodings is None:
            self.encodings = [
                "utf-8",  # Most common encoding for modern text files
                "utf-8-sig",  # UTF-8 with BOM
                "latin-1",  # Also known as ISO-8859-1, common in Western Europe
                "iso-8859-1",  # ISO Latin 1
                "cp1252",  # Windows-1252, common on Windows systems
                "ascii",  # Basic ASCII
            ]


@dataclass
class UISettings:
    """User interface configuration and state."""

    language_list_max_height: int = 140
    progress_bar_min_width: int = 200
    enable_alternating_row_colors: bool = True
    show_file_icons: bool = True
    auto_expand_directories: bool = False


@dataclass
class WorkerConfig:
    """Configuration for the background worker thread."""

    filter_settings: FilterSettings
    generation_options: GenerationOptions
    estimated_total_files: int = 0
    progress_update_interval: int = 10


# --- Helper Function for Ignore Patterns ---
def load_ignore_patterns(directory: Path) -> pathspec.PathSpec | None:
    """Loads ignore patterns from various ignore files in the specified directory."""
    patterns = []
    ignore_files = [".gitignore", ".npmignore", ".dockerignore"]
    for ig_file in ignore_files:
        ignore_path = directory / ig_file
        if ignore_path.is_file():
            try:
                with ignore_path.open("r", encoding="utf-8", errors="ignore") as f:
                    patterns.extend(f.readlines())
            except Exception as e:
                logging.warning(f"Could not read {ignore_path}: {e}")

    # Also load .git/info/exclude if .git exists
    git_dir = directory / ".git"
    if git_dir.is_dir():
        exclude_path = git_dir / "info" / "exclude"
        if exclude_path.is_file():
            try:
                with exclude_path.open("r", encoding="utf-8", errors="ignore") as f:
                    patterns.extend(f.readlines())
            except Exception as e:
                logging.warning(f"Could not read {exclude_path}: {e}")

    if patterns:
        try:
            return pathspec.PathSpec.from_lines(
                pathspec.patterns.GitWildMatchPattern, patterns  # type: ignore[attr-defined]
            )
        except Exception as e:
            logging.error(f"Error parsing ignore patterns from {directory}: {e}")
            return None
    return None


# --- Shared utility functions ---
def is_binary_file(filepath: Path) -> bool:
    """Check if a file is likely binary by looking for null bytes."""
    CHUNK_SIZE = 1024
    try:
        with filepath.open("rb") as f:
            chunk = f.read(CHUNK_SIZE)
        return b"\0" in chunk
    except OSError as e:
        logging.warning(
            f"Could not read start of file {filepath} to check if binary: {e}"
        )
        return True
    except Exception as e:
        logging.error(
            f"Unexpected error checking if file is binary {filepath}: {e}",
            exc_info=True,
        )
        return True


def is_likely_text_file(filepath: Path) -> bool:
    """
    Detect if file is likely text based on name patterns and content.
    """
    # Known text filenames without extensions
    text_filenames = {
        "readme",
        "license",
        "licence",
        "changelog",
        "changes",
        "authors",
        "contributors",
        "copying",
        "install",
        "news",
        "todo",
        "version",
        "dockerfile",
        "makefile",
        "rakefile",
        "gemfile",
        "pipfile",
        "procfile",
        "vagrantfile",
        "jenkinsfile",
        "cname",
        "notice",
        "manifest",
        "copyright",
    }

    # Check if it's a known text filename (case insensitive)
    if filepath.name.lower() in text_filenames:
        return not is_binary_file(filepath)

    # Dotfiles are often config files (but skip .git, .DS_Store, etc.)
    if filepath.name.startswith(".") and len(filepath.name) > 1:
        # Skip known binary or special dotfiles
        skip_dotfiles = {
            ".git",
            ".ds_store",
            ".pyc",
            ".pyo",
            ".pyd",
            ".so",
            ".dylib",
            ".dll",
        }
        if filepath.name.lower() not in skip_dotfiles:
            return not is_binary_file(filepath)

    # Files with no extension that aren't binary
    if not filepath.suffix:
        return not is_binary_file(filepath)

    # Files with unusual extensions that might be text
    possible_text_extensions = {
        ".ini",
        ".cfg",
        ".conf",
        ".config",
        ".properties",
        ".env",
        ".envrc",
        ".ignore",
        ".keep",
        ".gitkeep",
        ".npmignore",
        ".dockerignore",
        ".editorconfig",
        ".flake8",
        ".pylintrc",
        ".prettierrc",
        ".eslintrc",
        ".stylelintrc",
        ".babelrc",
        ".npmrc",
        ".yarnrc",
        ".nvmrc",
        ".ruby-version",
        ".python-version",
        ".node-version",
        ".terraform",
        ".tf",
        ".tfvars",
        ".ansible",
        ".playbook",
        ".vault",
        ".j2",
        ".jinja",
        ".jinja2",
        ".template",
        ".tmpl",
        ".tpl",
        ".mustache",
        ".hbs",
        ".handlebars",
    }

    if filepath.suffix.lower() in possible_text_extensions:
        return not is_binary_file(filepath)

    return False


def build_filter_sets(ext_dict: Dict[str, List[str]]) -> Tuple[Set[str], Set[str]]:
    """Compiles all known extensions and filenames into sets for quick lookup."""
    by_ext: Set[str] = set()
    by_name: Set[str] = set()
    for exts in ext_dict.values():
        for e in exts:
            (by_ext if e.startswith(".") else by_name).add(e.lower())
    return by_ext, by_name


def matches_file_type(
    filepath: Path,
    selected_exts: Set[str],
    selected_names: Set[str],
    all_exts: Set[str],
    all_names: Set[str],
    handle_other: bool,
) -> bool:
    """Check if a file path matches the compiled filter sets."""
    file_ext = filepath.suffix.lower()
    file_name = filepath.name.lower()

    if file_name in selected_names:
        return True
    if file_ext in selected_exts:
        return True

    # Handle "Other Text Files" logic
    if handle_other:
        # Check if the file does NOT match any of the known file types
        if file_name not in all_names and file_ext not in all_exts:
            return is_likely_text_file(filepath)

    return False


# --- Worker Class for Background Processing ---
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

    def cancel(self) -> None:
        """Signals the worker to stop processing."""
        self._is_cancelled = True
        logging.info("Cancellation requested for worker.")

    def get_file_content(self, filepath: Path) -> str | None:
        """
        Safely read the content of a non-binary text file, trying multiple encodings.
        Returns None if the file is binary, cannot be read, or causes decoding errors.
        Catches MemoryError and falls back to chunked reading.
        """
        if is_binary_file(filepath):
            logging.warning(
                f"Skipping binary file detected during read: {filepath.name}"
            )
            return None

        # Get the list of encodings to try from config, or use default
        encodings = self.config.generation_options.encodings or [
            self.config.generation_options.default_encoding
        ]

        # Track the last exception for better error reporting
        last_error = None

        for encoding in encodings:
            try:
                try:
                    # Try reading the file with the current encoding
                    content = filepath.read_text(encoding=encoding, errors="strict")
                except MemoryError:
                    logging.warning(
                        f"MemoryError reading {filepath}, falling back to chunked read with {encoding}."
                    )
                    content = ""
                    with filepath.open("r", encoding=encoding, errors="strict") as f:
                        for chunk in iter(lambda: f.read(1024 * 1024), ""):
                            content += chunk

                # If we get here, the file was successfully read with this encoding
                if not content.strip():  # Skip empty or whitespace-only files
                    logging.info(f"Skipping empty file: {filepath.name}")
                    return None

                # Log which encoding worked for this file
                if encoding.lower() != "utf-8":
                    logging.info(
                        f"Successfully read {filepath.name} with {encoding} encoding"
                    )

                return content

            except UnicodeDecodeError as e:
                last_error = f"Failed to decode with {encoding}: {e}"
                continue  # Try the next encoding

            except (PermissionError, FileNotFoundError, OSError) as e:
                # These errors are not encoding-related, so we can stop trying
                logging.warning(f"Error reading {filepath.name}: {e}")
                return None

        # If we get here, all encodings failed
        logging.warning(
            f"Skipping file {filepath.name} - could not decode with any encoding. "
            f"Last error: {last_error}"
        )
        return None

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
                    file_content = self.get_file_content(full_path)
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

    @QtCore.pyqtSlot()
    def run(self) -> None:
        """Main execution method for the worker thread."""
        import tempfile
        import shutil

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
                    total_files += self.count_directory_recursive(
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
                            file_content = self.get_file_content(path)
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
                        self.process_directory_recursive(
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


# --- Main Application Window ---
class FileConcatenator(QtWidgets.QMainWindow):
    """
    A PyQt6-based graphical application for concatenating multiple files with language filtering.
    """

    PATH_ROLE = QtCore.Qt.ItemDataRole.UserRole + 1
    LANGUAGE_ROLE = QtCore.Qt.ItemDataRole.UserRole + 2

    def __init__(self, working_dir: Optional[Path] = None) -> None:
        super().__init__()
        self.initial_base_dir = (working_dir or Path.cwd()).resolve()
        self.working_dir = self.initial_base_dir
        self.setWindowTitle(f"SOTA Concatenator - [{self.working_dir.name}]")
        self.resize(700, 650)

        self.ignore_spec = load_ignore_patterns(self.working_dir)
        self.icon_provider = QtWidgets.QFileIconProvider()

        # Load global gitignore
        global_patterns = []
        try:
            global_ignore = (
                subprocess.check_output(["git", "config", "--get", "core.excludesFile"])
                .decode()
                .strip()
            )
            global_path = Path(global_ignore).expanduser()
            if global_path.is_file():
                with global_path.open("r", encoding="utf-8", errors="ignore") as f:
                    global_patterns = f.readlines()
        except Exception as e:
            logging.warning(f"Could not load global gitignore: {e}")
        self.global_ignore_spec = (
            pathspec.PathSpec.from_lines(
                pathspec.patterns.GitWildMatchPattern, global_patterns
            )
            if global_patterns
            else None
        )

        self.worker_thread: Optional[QtCore.QThread] = None
        self.worker: Optional[GeneratorWorker] = None
        self.is_generating = False

        # Updated comprehensive language extensions
        # Updated comprehensive language extensions
        self.language_extensions: Dict[str, List[str]] = {
            "Python": [
                ".py",
                ".pyw",
                ".pyx",
                ".pyi",
                "requirements.txt",
                "setup.py",
                "setup.cfg",
                "pyproject.toml",
                "pipfile",
            ],
            "JavaScript/TypeScript": [
                ".js",
                ".jsx",
                ".ts",
                ".tsx",
                ".mjs",
                ".cjs",
                "package.json",
                "package-lock.json",
                "yarn.lock",
            ],
            "Web Frontend": [
                ".html",
                ".htm",
                ".css",
                ".scss",
                ".sass",
                ".less",
                ".vue",
                ".svelte",
                ".astro",
            ],
            "Java/Kotlin": [
                ".java",
                ".kt",
                ".kts",
                ".gradle",
                "pom.xml",
                "build.gradle",
                "gradle.properties",
            ],
            "C/C++": [
                ".c",
                ".cpp",
                ".cxx",
                ".cc",
                ".h",
                ".hpp",
                ".hxx",
                ".cmake",
                "makefile",
                "cmakelists.txt",
            ],
            "C#/.NET": [".cs", ".fs", ".vb", ".csproj", ".fsproj", ".vbproj", ".sln"],
            "Ruby": [
                ".rb",
                ".rake",
                ".gemspec",
                ".ru",
                "gemfile",
                "gemfile.lock",
                "rakefile",
            ],
            "PHP": [
                ".php",
                ".phtml",
                ".php3",
                ".php4",
                ".php5",
                "composer.json",
                "composer.lock",
            ],
            "Go": [".go", ".mod", ".sum", "go.mod", "go.sum"],
            "Rust": [".rs", "cargo.toml", "cargo.lock"],
            "Swift/Objective-C": [
                ".swift",
                ".m",
                ".mm",
                ".h",
                "package.swift",
                "podfile",
                "podfile.lock",
            ],
            "Shell Scripts": [".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd"],
            "Config & Data": [
                ".json",
                ".yaml",
                ".yml",
                ".toml",
                ".xml",
                ".ini",
                ".cfg",
                ".conf",
                ".config",
                ".properties",
                ".plist",
                ".env",
                ".envrc",
            ],
            "Documentation": [
                ".md",
                ".markdown",
                ".rst",
                ".txt",
                ".adoc",
                ".org",
                "readme",
                "changelog",
                "license",
                "authors",
            ],
            "DevOps & CI": [
                ".dockerfile",
                "dockerfile",
                ".dockerignore",
                "docker-compose.yml",
                "docker-compose.yaml",
                ".travis.yml",
                ".gitlab-ci.yml",
                ".github",
                ".circleci",
                ".appveyor.yml",
                ".azure-pipelines.yml",
                "jenkinsfile",
                "vagrantfile",
                ".terraform",
                ".tf",
                ".tfvars",
            ],
            "Version Control": [
                ".gitignore",
                ".gitattributes",
                ".gitmodules",
                ".gitkeep",
            ],
            "Build \u0026 Package": [
                # ── Cross-language build systems ──────────────────────────────────────
                "makefile",  # Make
                "CMakeLists.txt",
                ".cmake",  # CMake
                ".ninja",  # Ninja
                ".bazel",
                ".bzl",
                "BUILD",  # Bazel / Starlark
                ".buck",  # Buck
                "meson.build",
                "meson_options.txt",
                "build.xml",
                "ivy.xml",  # Ant / Ivy
                "configure.ac",
                "configure.in",  # Autotools
                # ── JVM (Gradle / Maven / SBT) ───────────────────────────────────────
                "build.gradle",
                "settings.gradle",
                "gradle.properties",
                "gradlew",
                "gradlew.bat",
                "pom.xml",  # Maven
                "build.sbt",
                ".sbt",  # Scala sbt
                # ── .NET / NuGet ─────────────────────────────────────────────────────
                ".csproj",
                ".fsproj",
                ".vbproj",
                "packages.config",
                "nuget.config",
                # ── Swift Package Manager ────────────────────────────────────────────
                "Package.swift",
                "Package.resolved",
                # ── Go ───────────────────────────────────────────────────────────────
                "go.mod",
                "go.sum",
                "go.work",
                "go.work.sum",
                # ── Rust ─────────────────────────────────────────────────────────────
                "Cargo.toml",
                "Cargo.lock",
                # ── PHP / Composer ───────────────────────────────────────────────────
                "composer.json",
                "composer.lock",
                # ── Ruby / Bundler ───────────────────────────────────────────────────
                "Gemfile",
                "Gemfile.lock",
                "gemfile",
                "gemfile.lock",
                "rakefile",
                # ── Python packaging ─────────────────────────────────────────────────
                "pyproject.toml",  # PEP 517/518 (Poetry, Hatch, etc.)
                "Pipfile",
                "Pipfile.lock",  # Pipenv
                "poetry.lock",  # Poetry
                "requirements.txt",  # classic
                "requirements-dev.txt",
                "requirements-test.txt",
                "setup.py",
                "setup.cfg",
                "environment.yml",  # Conda
                # ── JavaScript / TypeScript / Node ecosystem ─────────────────────────
                # npm
                "package.json",
                "package-lock.json",
                "npm-shrinkwrap.json",
                # Yarn
                "yarn.lock",
                ".yarnrc",
                ".yarnrc.yml",
                # pnpm
                "pnpm-lock.yaml",
                "pnpm-workspace.yaml",
                ".pnpmfile.cjs",
                # bun
                "bun.lockb",
                # monorepo / workspace tools
                "rush.json",
                "lerna.json",  # Rush, Lerna
                "turbo.json",
                "turbo.yaml",  # Turborepo
                # ── Other language-specific lock / build files ───────────────────────
                "flake.lock",
                "flake.nix",  # Nix flakes
                "build.pyz",  # PEX / Pants
            ],
            "Other Text Files": [
                "*other*"
            ],  # Special category for unmatched text files
        }

        # Pre-compile all known extensions and filenames for fast lookups
        self.ALL_EXTENSIONS, self.ALL_FILENAMES = build_filter_sets(
            self.language_extensions
        )

        self.init_ui()
        self.populate_file_list()

    def init_ui(self) -> None:
        """Create and place all PyQt6 widgets."""
        central_widget = QtWidgets.QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QtWidgets.QVBoxLayout(central_widget)

        # --- Top Layout ---
        top_nav_layout = QtWidgets.QHBoxLayout()
        self.btn_up = QtWidgets.QPushButton()
        style = self.style()
        if style is not None:
            self.btn_up.setIcon(
                style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ArrowUp)
            )
        self.btn_up.setToolTip("Go to Parent Directory (Alt+Up)")
        self.btn_up.setShortcut(
            QtGui.QKeySequence(
                QtCore.Qt.KeyboardModifier.AltModifier.value
                | QtCore.Qt.Key.Key_Up.value
            )
        )
        self.btn_up.clicked.connect(self.go_up_directory)
        self.btn_up.setFixedWidth(
            self.btn_up.fontMetrics().horizontalAdvance(" Up ") * 2
        )
        top_nav_layout.addWidget(self.btn_up)

        self.current_path_label = QtWidgets.QLineEdit(str(self.working_dir))
        self.current_path_label.setReadOnly(True)
        self.current_path_label.setToolTip("Current Directory")
        top_nav_layout.addWidget(self.current_path_label)

        search_label = QtWidgets.QLabel("Search:")
        top_nav_layout.addWidget(search_label)
        self.search_entry = QtWidgets.QLineEdit()
        self.search_entry.setPlaceholderText("Filter items...")
        top_nav_layout.addWidget(self.search_entry)
        self.search_entry.textChanged.connect(self.refresh_files)
        top_nav_layout.addStretch()
        main_layout.addLayout(top_nav_layout)

        # --- Language Selection Section ---
        language_group = QtWidgets.QGroupBox("File Type Filters")
        language_layout = QtWidgets.QVBoxLayout(language_group)

        # Control buttons for language selection
        lang_buttons_layout = QtWidgets.QHBoxLayout()
        self.btn_select_all_languages = QtWidgets.QPushButton("All Types")
        self.btn_select_all_languages.clicked.connect(self.select_all_languages)
        self.btn_deselect_all_languages = QtWidgets.QPushButton("None")
        self.btn_deselect_all_languages.clicked.connect(self.deselect_all_languages)

        # Add common presets
        self.btn_code_only = QtWidgets.QPushButton("Code Only")
        self.btn_code_only.clicked.connect(self.select_code_only)
        self.btn_docs_config = QtWidgets.QPushButton("Docs & Config")
        self.btn_docs_config.clicked.connect(self.select_docs_config)

        lang_buttons_layout.addWidget(self.btn_select_all_languages)
        lang_buttons_layout.addWidget(self.btn_deselect_all_languages)
        lang_buttons_layout.addWidget(self.btn_code_only)
        lang_buttons_layout.addWidget(self.btn_docs_config)
        lang_buttons_layout.addStretch()
        language_layout.addLayout(lang_buttons_layout)

        # Language selection list
        self.language_list_widget = QtWidgets.QListWidget()
        self.language_list_widget.setMaximumHeight(140)
        self.language_list_widget.setAlternatingRowColors(True)

        # Populate language list with checkboxes
        for language_name in self.language_extensions.keys():
            item = QtWidgets.QListWidgetItem(language_name)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.CheckState.Checked)
            item.setData(self.LANGUAGE_ROLE, language_name)
            self.language_list_widget.addItem(item)

        self.language_list_widget.itemChanged.connect(self.refresh_files)
        language_layout.addWidget(self.language_list_widget)

        main_layout.addWidget(language_group)

        # --- File Tree Widget ---
        self.file_tree_widget = QtWidgets.QTreeWidget()
        self.file_tree_widget.setHeaderLabels(["Name"])
        self.file_tree_widget.setColumnCount(1)
        self.file_tree_widget.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.file_tree_widget.itemDoubleClicked.connect(self.handle_item_double_click)
        self.file_tree_widget.itemExpanded.connect(self.populate_children)
        self.file_tree_widget.itemChanged.connect(self.handle_check_change)
        self.file_tree_widget.setAlternatingRowColors(True)
        main_layout.addWidget(self.file_tree_widget)

        # --- Bottom Layout ---
        bottom_layout = QtWidgets.QHBoxLayout()
        self.btn_select_all = QtWidgets.QPushButton("Select All")
        self.btn_select_all.clicked.connect(self.select_all)
        bottom_layout.addWidget(self.btn_select_all)

        self.btn_deselect_all = QtWidgets.QPushButton("Deselect All")
        self.btn_deselect_all.clicked.connect(self.deselect_all)
        bottom_layout.addWidget(self.btn_deselect_all)
        bottom_layout.addStretch()

        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setMinimumWidth(200)
        self.progress_bar.setFormat("%p%")
        bottom_layout.addWidget(self.progress_bar)

        self.btn_cancel = QtWidgets.QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.cancel_generation)
        self.btn_cancel.setEnabled(False)
        bottom_layout.addWidget(self.btn_cancel)

        self.btn_generate = QtWidgets.QPushButton("Generate File")
        self.btn_generate.clicked.connect(self.start_generate_file)
        bottom_layout.addWidget(self.btn_generate)
        main_layout.addLayout(bottom_layout)

        self.update_ui_state()

    def get_selected_filter_sets(self) -> Tuple[Set[str], Set[str], bool]:
        """Get the compiled sets of selected extensions and filenames."""
        selected_exts: Set[str] = set()
        selected_names: Set[str] = set()
        handle_other = False

        for i in range(self.language_list_widget.count()):
            item = self.language_list_widget.item(i)
            assert item is not None
            if item.checkState() == QtCore.Qt.CheckState.Checked:
                language_name = item.data(self.LANGUAGE_ROLE)
                if language_name == "Other Text Files":
                    handle_other = True
                    continue

                if language_name in self.language_extensions:
                    for e in self.language_extensions[language_name]:
                        (selected_exts if e.startswith(".") else selected_names).add(
                            e.lower()
                        )

        return selected_exts, selected_names, handle_other

    def get_selected_language_names(self) -> List[str]:
        """Get names of selected language types for display purposes."""
        selected_names: List[str] = []

        for i in range(self.language_list_widget.count()):
            item = self.language_list_widget.item(i)
            assert item is not None
            if item.checkState() == QtCore.Qt.CheckState.Checked:
                language_name = item.data(self.LANGUAGE_ROLE)
                selected_names.append(language_name)

        return selected_names

    def select_all_languages(self) -> None:
        """Select all language types."""
        if self.is_generating:
            return
        for i in range(self.language_list_widget.count()):
            item = self.language_list_widget.item(i)
            assert item is not None
            item.setCheckState(QtCore.Qt.CheckState.Checked)

    def deselect_all_languages(self) -> None:
        """Deselect all language types."""
        if self.is_generating:
            return
        for i in range(self.language_list_widget.count()):
            item = self.language_list_widget.item(i)
            assert item is not None
            item.setCheckState(QtCore.Qt.CheckState.Unchecked)

    def select_code_only(self) -> None:
        """Select only programming language categories."""
        if self.is_generating:
            return
        code_categories = {
            "Python",
            "JavaScript/TypeScript",
            "Web Frontend",
            "Java/Kotlin",
            "C/C++",
            "C#/.NET",
            "Ruby",
            "PHP",
            "Go",
            "Rust",
            "Swift/Objective-C",
            "Shell Scripts",
        }
        for i in range(self.language_list_widget.count()):
            item = self.language_list_widget.item(i)
            assert item is not None
            language_name = item.data(self.LANGUAGE_ROLE)
            if language_name in code_categories:
                item.setCheckState(QtCore.Qt.CheckState.Checked)
            else:
                item.setCheckState(QtCore.Qt.CheckState.Unchecked)

    def select_docs_config(self) -> None:
        """Select documentation and configuration categories."""
        if self.is_generating:
            return
        docs_config_categories = {
            "Documentation",
            "Config & Data",
            "DevOps & CI",
            "Version Control",
            "Build & Package",
            "Other Text Files",
        }
        for i in range(self.language_list_widget.count()):
            item = self.language_list_widget.item(i)
            assert item is not None
            language_name = item.data(self.LANGUAGE_ROLE)
            if language_name in docs_config_categories:
                item.setCheckState(QtCore.Qt.CheckState.Checked)
            else:
                item.setCheckState(QtCore.Qt.CheckState.Unchecked)

    def update_ui_state(self) -> None:
        """Updates UI elements based on the current state."""
        try:
            display_path = self.working_dir.relative_to(self.initial_base_dir)
            title_path = (
                f".../{display_path}"
                if display_path != Path(".")
                else self.initial_base_dir.name
            )
        except ValueError:
            title_path = str(self.working_dir)
        self.setWindowTitle(f"SOTA Concatenator - [{title_path}]")
        self.current_path_label.setText(str(self.working_dir))
        self.current_path_label.setCursorPosition(0)
        is_root = self.working_dir.parent == self.working_dir
        self.btn_up.setEnabled(not is_root and not self.is_generating)

    def set_controls_enabled(self, enabled: bool) -> None:
        """Enable/disable controls during generation."""
        self.btn_generate.setEnabled(enabled)
        self.btn_select_all.setEnabled(enabled)
        self.btn_deselect_all.setEnabled(enabled)
        self.btn_select_all_languages.setEnabled(enabled)
        self.btn_deselect_all_languages.setEnabled(enabled)
        self.btn_code_only.setEnabled(enabled)
        self.btn_docs_config.setEnabled(enabled)
        self.file_tree_widget.setEnabled(enabled)
        self.language_list_widget.setEnabled(enabled)
        self.search_entry.setEnabled(enabled)
        is_root = self.working_dir.parent == self.working_dir
        self.btn_up.setEnabled(enabled and not is_root)
        self.btn_cancel.setEnabled(not enabled)

    def populate_file_list(self) -> None:
        """Populate the tree widget with files and directories."""
        self.file_tree_widget.clear()
        self.populate_directory(self.working_dir, None)

    def add_dir_node(
        self, parent_item: Optional[QtWidgets.QTreeWidgetItem], path: Path
    ) -> QtWidgets.QTreeWidgetItem:
        """Adds a directory node to the tree, with a dummy child to make it expandable."""
        node = QtWidgets.QTreeWidgetItem([path.name])
        node.setFlags(
            node.flags()
            | QtCore.Qt.ItemFlag.ItemIsUserCheckable
            | QtCore.Qt.ItemFlag.ItemIsAutoTristate
        )
        node.setCheckState(0, QtCore.Qt.CheckState.Unchecked)
        node.setData(0, self.PATH_ROLE, path)
        node.setIcon(
            0, self.icon_provider.icon(QtWidgets.QFileIconProvider.IconType.Folder)
        )

        # Add a fake child to make the expander arrow show up
        node.addChild(QtWidgets.QTreeWidgetItem())

        if parent_item:
            parent_item.addChild(node)
        else:
            self.file_tree_widget.addTopLevelItem(node)
        return node

    def add_file_node(
        self, parent_item: Optional[QtWidgets.QTreeWidgetItem], path: Path
    ) -> None:
        """Adds a file node to the tree."""
        try:
            qfileinfo = QtCore.QFileInfo(str(path))
            specific_icon = self.icon_provider.icon(qfileinfo)
        except Exception:
            specific_icon = QtGui.QIcon()

        item_icon = (
            specific_icon
            if not specific_icon.isNull()
            else self.icon_provider.icon(QtWidgets.QFileIconProvider.IconType.File)
        )
        item = QtWidgets.QTreeWidgetItem([path.name])
        item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, QtCore.Qt.CheckState.Unchecked)
        item.setData(0, self.PATH_ROLE, path)
        item.setIcon(0, item_icon)

        if parent_item:
            parent_item.addChild(item)
        else:
            self.file_tree_widget.addTopLevelItem(item)

    @QtCore.pyqtSlot(QtWidgets.QTreeWidgetItem)
    def populate_children(self, item: QtWidgets.QTreeWidgetItem) -> None:
        """Populates the children of a directory item when it's expanded."""
        # Check if it's the first expansion (dummy child is present)
        if not (
            item.childCount() > 0 and item.child(0).data(0, self.PATH_ROLE) is None
        ):
            return  # Already populated

        blocked = self.file_tree_widget.signalsBlocked()
        self.file_tree_widget.blockSignals(True)

        item.takeChildren()  # Remove the dummy child

        path: Path | None = item.data(0, self.PATH_ROLE)
        if path and os.path.isdir(
            path
        ):  # Use os.path.isdir to follow symlinks if necessary
            self.populate_directory(path, item)

        state = item.checkState(0)
        if state != QtCore.Qt.CheckState.PartiallyChecked:
            self._set_children_check_state(item, state)
        self._update_parent_check_state(item)

        self.file_tree_widget.blockSignals(blocked)

        # Manually propagate up
        parent = item.parent()
        while parent:
            self._update_parent_check_state(parent)
            parent = parent.parent()

    def populate_directory(
        self, directory: Path, parent_item: Optional[QtWidgets.QTreeWidgetItem]
    ) -> None:
        """Populate the tree widget with files and directories for one level, rejecting paths outside root."""
        selected_exts, selected_names, handle_other = self.get_selected_filter_sets()
        search_text = self.search_entry.text().lower().strip()

        try:
            entries = []
            for entry in os.scandir(directory):
                item_path = Path(entry.path)
                try:
                    resolved = item_path.resolve()
                    if not str(resolved).startswith(str(self.working_dir.resolve())):
                        logging.warning(
                            f"Rejected path outside project root: {resolved}"
                        )
                        continue
                except Exception as e:
                    logging.warning(f"Error resolving path {item_path}: {e}")
                    continue

                # Use relative path for ignore checks if possible
                try:
                    relative_path = item_path.relative_to(self.working_dir)
                    relative_path_str_for_ignore = str(relative_path)
                except ValueError:
                    relative_path_str_for_ignore = entry.name

                if entry.is_dir(
                    follow_symlinks=False
                ) and not relative_path_str_for_ignore.endswith("/"):
                    relative_path_str_for_ignore += "/"

                if self.ignore_spec and self.ignore_spec.match_file(
                    relative_path_str_for_ignore
                ):
                    continue

                if entry.name.startswith("."):
                    continue

                if search_text and search_text not in entry.name.lower():
                    continue

                try:
                    if not os.access(entry.path, os.R_OK):
                        continue
                    if entry.is_dir() and not os.access(entry.path, os.X_OK):
                        continue
                except OSError:
                    continue

                entries.append((entry, item_path))

            entries.sort(
                key=lambda x: (not x[0].is_dir(follow_symlinks=True), x[0].name.lower())
            )

            for entry, item_path in entries:
                if entry.is_dir(follow_symlinks=True):
                    self.add_dir_node(parent_item, item_path)
                elif entry.is_file(follow_symlinks=True):
                    if not (
                        selected_exts or selected_names or handle_other
                    ) or matches_file_type(
                        item_path,
                        selected_exts,
                        selected_names,
                        self.ALL_EXTENSIONS,
                        self.ALL_FILENAMES,
                        handle_other,
                    ):
                        self.add_file_node(parent_item, item_path)

        except PermissionError as e:
            logging.error(f"Permission denied accessing directory: {directory}. {e}")
            if parent_item:
                parent_item.setDisabled(True)
        except Exception as e:
            logging.error(f"Error listing directory {directory}: {e}", exc_info=True)
            if parent_item:
                parent_item.setDisabled(True)

    def refresh_files(self) -> None:
        """Refresh list (reload ignores)."""
        if self.is_generating:
            return
        self.ignore_spec = load_ignore_patterns(self.working_dir)
        self.populate_file_list()

    def handle_item_double_click(
        self, item: QtWidgets.QTreeWidgetItem, column: int
    ) -> None:
        """Navigate into directory."""
        if self.is_generating:
            return
        path_data = item.data(0, self.PATH_ROLE)
        if path_data and isinstance(path_data, Path):
            try:
                st = os.stat(path_data)
                if stat.S_ISDIR(st.st_mode):
                    _ = list(os.scandir(path_data))
                    self.working_dir = path_data.resolve()
                    logging.info(f"Navigated into directory: {self.working_dir}")
                    self.refresh_files()
                    self.search_entry.clear()
            except PermissionError:
                logging.warning(
                    f"Permission denied trying to navigate into {path_data}"
                )
                QtWidgets.QMessageBox.warning(
                    self,
                    "Access Denied",
                    f"Cannot open directory:\n{path_data.name}\n\nPermission denied.",
                )
            except FileNotFoundError:
                logging.warning(
                    f"Directory not found (deleted?) on double click: {path_data}"
                )
                QtWidgets.QMessageBox.warning(
                    self, "Not Found", f"Directory not found:\n{path_data.name}"
                )
                self.refresh_files()
            except Exception as e:
                logging.error(
                    f"Error navigating into directory {path_data}: {e}", exc_info=True
                )
                QtWidgets.QMessageBox.warning(
                    self,
                    "Navigation Error",
                    f"Could not open directory:\n{path_data.name}\n\n{e}",
                )

    def go_up_directory(self) -> None:
        """Navigate up."""
        if self.is_generating:
            return
        parent_dir = self.working_dir.parent
        if parent_dir != self.working_dir:
            try:
                _ = list(os.scandir(parent_dir))
                self.working_dir = parent_dir.resolve()
                logging.info(f"Navigated up to directory: {self.working_dir}")
                self.refresh_files()
                self.search_entry.clear()
            except PermissionError:
                logging.warning(
                    f"Permission denied trying to navigate up to {parent_dir}"
                )
                QtWidgets.QMessageBox.warning(
                    self,
                    "Access Denied",
                    f"Cannot open parent directory:\n{parent_dir}\n\nPermission denied.",
                )
            except FileNotFoundError:
                logging.warning(f"Parent directory not found (deleted?): {parent_dir}")
                QtWidgets.QMessageBox.warning(
                    self, "Not Found", f"Parent directory not found:\n{parent_dir}"
                )
            except Exception as e:
                logging.error(
                    f"Error navigating up to directory {parent_dir}: {e}", exc_info=True
                )
                QtWidgets.QMessageBox.warning(
                    self,
                    "Navigation Error",
                    f"Could not open parent directory:\n{parent_dir}\n\n{e}",
                )

    def select_all(self) -> None:
        """Select all checkable items."""
        if self.is_generating:
            return
        self._set_all_items_checked(True)

    def deselect_all(self) -> None:
        """Deselect all checkable items."""
        if self.is_generating:
            return
        self._set_all_items_checked(False)

    def _set_all_items_checked(self, checked: bool) -> None:
        """Recursively set the checked state of all items."""
        check_state = (
            QtCore.Qt.CheckState.Checked if checked else QtCore.Qt.CheckState.Unchecked
        )
        for i in range(self.file_tree_widget.topLevelItemCount()):
            item = self.file_tree_widget.topLevelItem(i)
            if item is not None:
                self._set_item_checked_recursive(item, check_state)

    def _set_item_checked_recursive(
        self, item: QtWidgets.QTreeWidgetItem, check_state: QtCore.Qt.CheckState
    ) -> None:
        """Recursively set the checked state of an item and its children."""
        if item.flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable:
            item.setCheckState(0, check_state)
        for i in range(item.childCount()):
            child = item.child(i)
            if child is not None:
                self._set_item_checked_recursive(child, check_state)

    def handle_check_change(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        if column != 0:
            return
        state = item.checkState(0)
        if state != QtCore.Qt.CheckState.PartiallyChecked:
            self._set_children_check_state(item, state)
        parent = item.parent()
        while parent:
            self._update_parent_check_state(parent)
            parent = parent.parent()

    def _set_children_check_state(
        self, item: QtWidgets.QTreeWidgetItem, state: QtCore.Qt.CheckState
    ) -> None:
        for i in range(item.childCount()):
            child = item.child(i)
            if child.flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable:
                child.setCheckState(0, state)
            self._set_children_check_state(child, state)

    def _update_parent_check_state(self, parent: QtWidgets.QTreeWidgetItem) -> None:
        checked_count = 0
        total_count = 0
        has_partial = False
        for i in range(parent.childCount()):
            child = parent.child(i)
            if child.flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable:
                total_count += 1
                child_state = child.checkState(0)
                if child_state == QtCore.Qt.CheckState.Checked:
                    checked_count += 1
                elif child_state == QtCore.Qt.CheckState.PartiallyChecked:
                    has_partial = True
        if total_count == 0:
            return
        if checked_count == total_count and not has_partial:
            parent.setCheckState(0, QtCore.Qt.CheckState.Checked)
        elif checked_count == 0 and not has_partial:
            parent.setCheckState(0, QtCore.Qt.CheckState.Unchecked)
        else:
            parent.setCheckState(0, QtCore.Qt.CheckState.PartiallyChecked)

    def _collect_selected_paths(self, item: QtWidgets.QTreeWidgetItem) -> List[Path]:
        """Recursively collect all checked file paths from the tree, rejecting paths outside project root."""
        paths: List[Path] = []
        item_path = item.data(0, self.PATH_ROLE)
        if item_path and isinstance(item_path, Path):
            try:
                resolved = item_path.resolve()
                # Reject if outside project root using proper path comparison
                try:
                    if not resolved.is_relative_to(self.working_dir.resolve()):
                        logging.warning(
                            f"Rejected path outside project root: {resolved}"
                        )
                        return paths
                except AttributeError:
                    # Fallback for Python < 3.9 - use Path.parts for comparison
                    try:
                        working_dir_parts = self.working_dir.resolve().parts
                        resolved_parts = resolved.parts
                        if (
                            resolved_parts[: len(working_dir_parts)]
                            != working_dir_parts
                        ):
                            logging.warning(
                                f"Rejected path outside project root (fallback): {resolved}"
                            )
                            return paths
                    except Exception as e:
                        logging.warning(f"Error in path comparison: {e}")
                        return paths
            except Exception as e:
                logging.warning(f"Error resolving path {item_path}: {e}")
                return paths
            if item.checkState(0) == QtCore.Qt.CheckState.Checked:
                paths.append(item_path)
            else:
                for i in range(item.childCount()):
                    child = item.child(i)
                    if child is not None:
                        paths.extend(self._collect_selected_paths(child))
        return paths

    def start_generate_file(self) -> None:
        """Initiates the file generation process in a background thread."""
        if self.is_generating:
            logging.warning("Generation process already running.")
            return

        selected_exts, selected_names, handle_other = self.get_selected_filter_sets()
        if not selected_exts and not selected_names and not handle_other:
            QtWidgets.QMessageBox.warning(
                self, "No File Types", "Please select at least one file type."
            )
            return

        selected_paths = self._collect_selected_paths_recursive()

        if not selected_paths:
            QtWidgets.QMessageBox.warning(
                self, "No Selection", "Please select at least one file or directory."
            )
            return

        self.is_generating = True
        self.set_controls_enabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setFormat("Starting...")

        # Create configuration objects
        filter_settings = FilterSettings(
            selected_extensions=selected_exts,
            selected_filenames=selected_names,
            all_known_extensions=self.ALL_EXTENSIONS,
            all_known_filenames=self.ALL_FILENAMES,
            handle_other_text_files=handle_other,
            ignore_spec=self.ignore_spec,
            global_ignore_spec=self.global_ignore_spec,
            search_text=self.search_entry.text(),
        )

        generation_options = GenerationOptions(
            selected_paths=selected_paths, base_directory=self.working_dir
        )

        worker_config = WorkerConfig(
            filter_settings=filter_settings, generation_options=generation_options
        )

        self.worker_thread = QtCore.QThread()
        self.worker = GeneratorWorker(worker_config)
        assert self.worker is not None
        assert self.worker_thread is not None
        self.worker.moveToThread(self.worker_thread)

        self.worker.pre_count_finished.connect(self.handle_pre_count)
        self.worker.progress_updated.connect(self.handle_progress_update)
        self.worker.status_updated.connect(self.handle_status_update)
        self.worker.finished.connect(self.handle_generation_finished)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.finished.connect(self.generation_cleanup)

        logging.info("Starting generator thread...")
        self.worker_thread.start()

    def _collect_selected_paths_recursive(self) -> List[Path]:
        """Collect all selected paths from the tree widget."""
        paths: List[Path] = []
        for i in range(self.file_tree_widget.topLevelItemCount()):
            item = self.file_tree_widget.topLevelItem(i)
            if item is not None:
                paths.extend(self._collect_selected_paths(item))
            else:
                logging.warning(f"Null item at index {i} in top level items")
        return paths

    @QtCore.pyqtSlot(int)
    def handle_pre_count(self, total_files: int) -> None:
        """Slot to handle the pre_count_finished signal."""
        logging.info(f"Received pre-count: {total_files}")
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")

    @QtCore.pyqtSlot(int)
    def handle_progress_update(self, value: int) -> None:
        """Slot to handle the progress_updated signal."""
        self.progress_bar.setValue(value)

    @QtCore.pyqtSlot(str)
    def handle_status_update(self, message: str) -> None:
        """Slot to handle the status_updated signal."""
        self.progress_bar.setFormat(message + " %p%")

    @QtCore.pyqtSlot(str, str)
    def handle_generation_finished(
        self, temp_file_path: str, error_message: str
    ) -> None:
        """Slot to handle the finished signal from the worker."""
        logging.info(f"Generator worker finished. Error: '{error_message}'")

        if not error_message:
            self.progress_bar.setValue(100)
            self.progress_bar.setFormat("Finalizing...")
        elif "cancel" in error_message.lower():
            self.progress_bar.setFormat("Cancelled")
        else:
            self.progress_bar.setFormat("Error")

        if error_message:
            if "cancel" not in error_message.lower():
                QtWidgets.QMessageBox.warning(
                    self, "Generation Error", f"An error occurred:\n{error_message}"
                )
        elif not temp_file_path:
            QtWidgets.QMessageBox.information(
                self,
                "Finished",
                "No processable content found in the selected items matching the filters.",
            )
        else:
            try:
                self.save_generated_file(temp_file_path)
            except Exception as e:
                error_message = str(e)
                QtWidgets.QMessageBox.critical(
                    self,
                    "Error Saving File",
                    f"Failed to save output file: {error_message}",
                )

    def generation_cleanup(self) -> None:
        """Slot called when the thread finishes, regardless of reason."""
        logging.info("Generator thread finished signal received. Cleaning up.")
        self.worker = None
        self.worker_thread = None
        self.is_generating = False
        self.set_controls_enabled(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")

    def cancel_generation(self) -> None:
        """Requests cancellation of the running worker."""
        if self.worker:
            logging.info("Cancel button clicked. Requesting worker cancellation.")
            self.worker.cancel()
            self.btn_cancel.setEnabled(False)
            self.progress_bar.setFormat("Cancelling...")
        else:
            logging.warning("Cancel clicked but no worker active.")

    def save_generated_file(self, temp_file_path: str) -> None:
        """Handles the save file dialog and writing the output."""
        # Try to find Desktop, with multiple fallback strategies
        desktop_path = None
        possible_desktop_paths = [
            Path.home() / "Desktop",
            Path.home() / "desktop",  # Linux sometimes uses lowercase
            Path.home() / "Bureau",  # French systems
            Path.home() / "Escritorio",  # Spanish systems
            Path.home() / "Área de Trabalho",  # Portuguese systems
        ]

        for path in possible_desktop_paths:
            if path.exists() and path.is_dir():
                desktop_path = path
                break

        # Fallback to home directory if no desktop found
        if not desktop_path:
            desktop_path = Path.home()
            logging.info("Desktop directory not found, using home directory as default")

        # Generate filename based on the current working directory name
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Use the actual directory name being processed
        dir_name = self.working_dir.name if self.working_dir.name else "files"

        # Include selected language types in filename (abbreviated)
        selected_langs = self.get_selected_language_names()
        if len(selected_langs) == len(self.language_extensions):
            lang_suffix = "all_types"
        elif len(selected_langs) <= 2:
            lang_suffix = "_".join(selected_langs)
        elif len(selected_langs) <= 4:
            lang_suffix = "_".join(selected_langs[:3]) + "_etc"
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

        default_path = desktop_path / initial_filename

        logging.info(f"Save dialog defaulting to: {default_path}")

        # Make the dialog application modal
        file_dialog = QtWidgets.QFileDialog(
            self,
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
                self, "Cancelled", "Save operation cancelled."
            )
            return

        try:
            output_path = Path(output_filename)

            # Prevent overwriting the running script
            if (
                "__file__" in globals()
                and output_path.resolve() == Path(__file__).resolve()
            ):
                QtWidgets.QMessageBox.critical(
                    self, "Error", "Cannot overwrite the running script file!"
                )
                return

            # Write header to the output file
            with atomic_write(
                output_path, mode="w", encoding="utf-8", overwrite=True
            ) as f:
                f.write(f"# Concatenated Files from: {self.working_dir}\n")
                f.write(
                    f"# Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                )
                f.write(f"# Total directory size: {self.working_dir.name}\n")

                # Show selected file types in a readable format
                selected_types = self.get_selected_language_names()
                if len(selected_types) == len(self.language_extensions):
                    f.write("# Selected file types: All types\n")
                else:
                    f.write(f"# Selected file types: {', '.join(selected_types)}\n")

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
                self,
                "Success",
                f"File generated successfully!\n\nSaved to:\n{output_filename}\n\nFile size: {output_path.stat().st_size:,} bytes",
            )
            logging.info(f"Successfully generated file: {output_filename}")

        except Exception as e:
            logging.error(
                f"Error writing output file {output_filename}: {e}", exc_info=True
            )
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Could not write output file:\n{output_filename}\n\n{e}"
            )
        finally:
            # Reset progress bar
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("%p%")

    def closeEvent(self, event: Optional[QtGui.QCloseEvent]) -> None:
        """Handle window close event, ensuring worker thread is stopped."""
        if event is None:
            return
        if self.is_generating and self.worker_thread and self.worker_thread.isRunning():
            reply = QtWidgets.QMessageBox.question(
                self,
                "Confirm Exit",
                "A generation task is running. Are you sure you want to exit?",
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No,
            )
            if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                logging.info(
                    "Window close requested during generation. Attempting cancellation."
                )
                if self.worker:
                    self.worker.cancel()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


if __name__ == "__main__":
    # Initialize application settings
    app_settings = AppSettings()

    QtCore.QCoreApplication.setApplicationName(app_settings.window_title)
    QtCore.QCoreApplication.setOrganizationName(app_settings.organization_name)
    QtCore.QCoreApplication.setApplicationVersion(app_settings.application_version)

    app = QtWidgets.QApplication(sys.argv)

    settings = QtCore.QSettings(app_settings.organization_name, "SOTAConcatenator")
    last_dir = settings.value("last_directory", str(Path.cwd()))

    selected_dir = QtWidgets.QFileDialog.getExistingDirectory(
        None, "Select Project Directory To Concatenate", last_dir
    )

    if selected_dir:
        working_dir = Path(selected_dir)
        settings.setValue("last_directory", selected_dir)
    else:
        logging.warning("No directory selected on startup. Exiting.")
        sys.exit(0)

    window = FileConcatenator(working_dir=working_dir)
    window.show()
    sys.exit(app.exec())
