"""Configuration dataclasses for the Source Stitcher application."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set
import pathspec

from .version import get_cached_version, get_cached_app_name

logger = logging.getLogger(__name__)


@dataclass
class AppSettings:
    """Application-level settings and configuration."""

    window_title: str = field(default_factory=lambda: f"{get_cached_app_name()}")
    organization_name: str = "YourOrg"
    application_version: str = field(default_factory=get_cached_version)
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
    # Ignore file preferences
    use_gitignore: bool = True  # Default ON for gitignore
    use_npmignore: bool = False  # Default OFF for npmignore
    use_dockerignore: bool = False  # Default OFF for dockerignore


@dataclass
class GenerationOptions:
    """Options for file generation and processing."""

    selected_paths: List[Path]
    base_directory: Path
    output_format: str = "markdown"
    include_file_stats: bool = True
    include_timestamp: bool = True
    max_file_size_mb: int = 100
    encodings: Optional[List[str]] = None
    default_encoding: str = "utf-8"
    line_ending: str = "\n"

    def __post_init__(self):
        logger.debug("Initializing GenerationOptions")
        if self.encodings is None:
            logger.debug("Encodings not provided, setting defaults.")
            self.encodings = [
                "utf-8",
                "utf-8-sig",
                "latin-1",
                "iso-8859-1",
                "cp1252",
                "ascii",
            ]
        logger.debug(f"GenerationOptions validation completed: {self}")


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
    selected_language_names: List[str] = field(default_factory=list)
    estimated_total_files: int = 0
    progress_update_interval: int = 10
    language_config_path: Optional[Path] = None
