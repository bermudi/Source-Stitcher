"""CLI configuration and validation."""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set
import pathspec

from ..config import FilterSettings, GenerationOptions
from ..language_definitions import get_language_extensions


@dataclass
class CLIConfig:
    """Configuration for CLI mode operation."""

    directory: Path
    output_file: Path
    include_types: Optional[List[str]] = None
    exclude_types: Optional[List[str]] = None
    include_extensions: Optional[List[str]] = None
    exclude_extensions: Optional[List[str]] = None
    respect_gitignore: bool = True
    ignore_file: Optional[Path] = None
    include_hidden: bool = False
    max_file_size_mb: int = 100
    recursive: bool = True
    verbose: bool = False
    quiet: bool = False
    log_level: str = "INFO"
    progress: bool = False
    output_format: str = "markdown"
    encoding: str = "utf-8"
    line_ending: str = "unix"
    include_stats: bool = True
    include_timestamp: bool = True
    overwrite: bool = False

    def __post_init__(self):
        """Initialize default values for list fields."""
        if self.include_types is None:
            self.include_types = []
        if self.exclude_types is None:
            self.exclude_types = []
        if self.include_extensions is None:
            self.include_extensions = []
        if self.exclude_extensions is None:
            self.exclude_extensions = []

    def to_filter_settings(self) -> FilterSettings:
        """Convert CLI configuration to FilterSettings object."""
        language_extensions = get_language_extensions()

        # Start with all known extensions and filenames
        all_extensions = set()
        all_filenames = set()

        for lang_name, extensions in language_extensions.items():
            for ext in extensions:
                if ext.startswith("."):
                    all_extensions.add(ext)
                else:
                    all_filenames.add(ext.lower())

        # Determine selected extensions and filenames based on CLI filters
        selected_extensions, selected_filenames = self._calculate_selected_files(
            language_extensions, all_extensions, all_filenames
        )

        # Handle ignore patterns
        ignore_spec = None
        if self.respect_gitignore:
            ignore_path = (
                self.ignore_file if self.ignore_file else self.directory / ".gitignore"
            )
            if ignore_path and ignore_path.exists():
                try:
                    with open(ignore_path, "r", encoding="utf-8") as f:
                        ignore_spec = pathspec.PathSpec.from_lines("gitwildmatch", f)
                except Exception:
                    pass  # Ignore errors, will be logged elsewhere

        # Handle other text files
        handle_other_text_files = not self.include_types and not self.include_extensions

        return FilterSettings(
            selected_extensions=selected_extensions,
            selected_filenames=selected_filenames,
            all_known_extensions=all_extensions,
            all_known_filenames=all_filenames,
            handle_other_text_files=handle_other_text_files,
            ignore_spec=ignore_spec,
            global_ignore_spec=None,
            search_text="",
            include_hidden=self.include_hidden,
        )

    def to_generation_options(self) -> GenerationOptions:
        """Convert CLI configuration to GenerationOptions object."""
        # Convert line ending format
        line_ending_map = {"unix": "\n", "windows": "\r\n", "mac": "\r"}
        line_ending = line_ending_map.get(self.line_ending, "\n")

        # Set up encodings list
        encodings = None
        if self.encoding != "utf-8":
            # Put the specified encoding first, then fallbacks
            encodings = [
                self.encoding,
                "utf-8",
                "utf-8-sig",
                "latin-1",
                "iso-8859-1",
                "cp1252",
                "ascii",
            ]

        return GenerationOptions(
            selected_paths=[self.directory],
            base_directory=self.directory,
            output_format=self.output_format,
            include_file_stats=self.include_stats,
            include_timestamp=self.include_timestamp,
            max_file_size_mb=self.max_file_size_mb,
            encodings=encodings,
            default_encoding=self.encoding,
            line_ending=line_ending,
            recursive=self.recursive,
        )

    def _calculate_selected_files(
        self,
        language_extensions: dict,
        all_extensions: Set[str],
        all_filenames: Set[str],
    ) -> tuple[Set[str], Set[str]]:
        """Calculate which extensions and filenames should be selected based on CLI filters."""
        selected_extensions = set()
        selected_filenames = set()

        # If include_types is specified, start with those
        if self.include_types:
            for type_name in self.include_types:
                # Find matching language (case-insensitive)
                for lang_name, extensions in language_extensions.items():
                    if (
                        type_name.lower() in lang_name.lower()
                        or lang_name.lower() in type_name.lower()
                    ):
                        for ext in extensions:
                            if ext.startswith("."):
                                selected_extensions.add(ext)
                            else:
                                selected_filenames.add(ext.lower())
                        break
        else:
            # If no include_types specified, start with all
            selected_extensions = all_extensions.copy()
            selected_filenames = all_filenames.copy()

        # Add explicitly included extensions
        if self.include_extensions:
            for ext in self.include_extensions:
                if not ext.startswith("."):
                    ext = "." + ext
                selected_extensions.add(ext)

        # Remove excluded types
        if self.exclude_types:
            for type_name in self.exclude_types:
                for lang_name, extensions in language_extensions.items():
                    if (
                        type_name.lower() in lang_name.lower()
                        or lang_name.lower() in type_name.lower()
                    ):
                        for ext in extensions:
                            if ext.startswith("."):
                                selected_extensions.discard(ext)
                            else:
                                selected_filenames.discard(ext.lower())
                        break

        # Remove explicitly excluded extensions
        if self.exclude_extensions:
            for ext in self.exclude_extensions:
                if not ext.startswith("."):
                    ext = "." + ext
                selected_extensions.discard(ext)

        return selected_extensions, selected_filenames
