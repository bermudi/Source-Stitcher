"""Configuration dataclasses for the Source Stitcher application."""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set
import pathspec


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
    encodings: Optional[List[str]] = None
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