#!/usr/bin/env python3
"""
Main entry point for the Source Stitcher application.
"""

import argparse
import logging
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set
import pathspec

from PyQt6 import QtCore, QtWidgets

from src.config import AppSettings, FilterSettings, GenerationOptions, WorkerConfig
from src.language_definitions import get_language_extensions
from src.main_window import FileConcatenator
from src.worker import GeneratorWorker

# Default logging configuration - will be reconfigured based on CLI args
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def configure_logging(verbose: bool = False, quiet: bool = False, log_level: str = "INFO", 
                     is_cli_mode: bool = False) -> None:
    """
    Configure logging based on CLI arguments for both CLI and GUI modes.
    
    Args:
        verbose: Enable verbose (DEBUG) logging
        quiet: Suppress all non-error output
        log_level: Specific log level (DEBUG, INFO, WARNING, ERROR)
        is_cli_mode: Whether running in CLI mode (affects output format)
    """
    # Determine the effective log level
    if quiet:
        level = logging.ERROR
    elif verbose:
        level = logging.DEBUG
    else:
        level_map = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR
        }
        level = level_map.get(log_level.upper(), logging.INFO)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Clear existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Create appropriate handler based on mode
    if is_cli_mode:
        # CLI mode: Use stderr for all logging to keep stdout clean for output
        handler = logging.StreamHandler(sys.stderr)
        if quiet:
            # In quiet mode, only show errors
            formatter = logging.Formatter("Error: %(message)s")
        elif verbose:
            # In verbose mode, show detailed information
            formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        else:
            # Normal CLI mode: clean format
            formatter = logging.Formatter("[%(levelname)s] %(message)s")
    else:
        # GUI mode: Use stdout with timestamp for debugging
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    
    handler.setLevel(level)
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    
    # Configure specific loggers for better control
    # Reduce noise from Qt and other libraries unless in debug mode
    if level > logging.DEBUG:
        logging.getLogger("PyQt6").setLevel(logging.WARNING)
        logging.getLogger("qt").setLevel(logging.WARNING)
    
    # Log the configuration for debugging
    if level <= logging.DEBUG:
        logging.debug(f"Logging configured - Level: {logging.getLevelName(level)}, "
                     f"CLI Mode: {is_cli_mode}, Verbose: {verbose}, Quiet: {quiet}")


class CLIProgressReporter:
    """
    Progress reporter for CLI mode that connects to worker signals.
    """
    
    def __init__(self, show_progress: bool = False, quiet: bool = False):
        self.show_progress = show_progress
        self.quiet = quiet
        self.total_files = 0
        self.processed_files = 0
        self.start_time = None
        
    def on_status_updated(self, status: str):
        """Handle status updates from worker."""
        if self.show_progress and not self.quiet:
            print(f"Status: {status}", file=sys.stderr)
        logging.info(f"Worker status: {status}")
    
    def on_progress_updated(self, progress: int):
        """Handle progress updates from worker."""
        if self.show_progress and not self.quiet:
            print(f"Progress: {progress}%", file=sys.stderr)
        logging.debug(f"Worker progress: {progress}%")
    
    def on_pre_count_finished(self, total_files: int):
        """Handle pre-count completion."""
        self.total_files = total_files
        if self.show_progress and not self.quiet:
            print(f"Found {total_files} files to process", file=sys.stderr)
        logging.info(f"Pre-count completed: {total_files} files found")
        
        # Record start time for statistics
        import time
        self.start_time = time.time()
    
    def on_file_processed(self, file_path: str):
        """Handle individual file processing (if available from worker)."""
        self.processed_files += 1
        if self.show_progress and not self.quiet and self.total_files > 0:
            percentage = (self.processed_files / self.total_files) * 100
            print(f"Processed: {self.processed_files}/{self.total_files} ({percentage:.1f}%)", 
                  file=sys.stderr)
        logging.debug(f"Processed file: {file_path}")
    
    def get_summary_stats(self, output_file: Path) -> dict:
        """Generate summary statistics for final output."""
        import time
        
        stats = {
            "total_files": self.total_files,
            "processed_files": self.processed_files,
            "processing_time": None,
            "output_size": 0
        }
        
        if self.start_time:
            stats["processing_time"] = time.time() - self.start_time
        
        if output_file.exists():
            stats["output_size"] = output_file.stat().st_size
        
        return stats
    
    def print_summary(self, output_file: Path):
        """Print final summary statistics."""
        if self.quiet:
            return
            
        stats = self.get_summary_stats(output_file)
        
        print(f"Successfully processed {stats['processed_files']} files", file=sys.stderr)
        print(f"Output written to: {output_file}", file=sys.stderr)
        print(f"Output file size: {stats['output_size']:,} bytes", file=sys.stderr)
        
        if stats["processing_time"]:
            print(f"Processing time: {stats['processing_time']:.2f} seconds", file=sys.stderr)
        
        logging.info(f"Processing completed successfully: {stats}")


@dataclass
class CLIConfig:
    """Configuration for CLI mode operation."""
    
    directory: Path
    output_file: Path
    include_types: List[str] = None
    exclude_types: List[str] = None
    include_extensions: List[str] = None
    exclude_extensions: List[str] = None
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
                if ext.startswith('.'):
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
            ignore_path = self.ignore_file if self.ignore_file else self.directory / '.gitignore'
            if ignore_path and ignore_path.exists():
                try:
                    with open(ignore_path, 'r', encoding='utf-8') as f:
                        ignore_spec = pathspec.PathSpec.from_lines('gitwildmatch', f)
                    logging.debug(f"Loaded ignore patterns from: {ignore_path}")
                except Exception as e:
                    logging.warning(f"Failed to read ignore file {ignore_path}: {e}")
        
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
            search_text=""
        )

    def to_generation_options(self) -> GenerationOptions:
        """Convert CLI configuration to GenerationOptions object."""
        # Convert line ending format
        line_ending_map = {
            "unix": "\n",
            "windows": "\r\n", 
            "mac": "\r"
        }
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
                "ascii"
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
            line_ending=line_ending
        )

    def _calculate_selected_files(self, language_extensions: dict, all_extensions: Set[str], 
                                all_filenames: Set[str]) -> tuple[Set[str], Set[str]]:
        """Calculate which extensions and filenames should be selected based on CLI filters."""
        selected_extensions = set()
        selected_filenames = set()
        
        # If include_types is specified, start with those
        if self.include_types:
            for type_name in self.include_types:
                # Find matching language (case-insensitive)
                for lang_name, extensions in language_extensions.items():
                    if type_name.lower() in lang_name.lower() or lang_name.lower() in type_name.lower():
                        for ext in extensions:
                            if ext.startswith('.'):
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
                if not ext.startswith('.'):
                    ext = '.' + ext
                selected_extensions.add(ext)
        
        # Remove excluded types
        if self.exclude_types:
            for type_name in self.exclude_types:
                for lang_name, extensions in language_extensions.items():
                    if type_name.lower() in lang_name.lower() or lang_name.lower() in type_name.lower():
                        for ext in extensions:
                            if ext.startswith('.'):
                                selected_extensions.discard(ext)
                            else:
                                selected_filenames.discard(ext.lower())
                        break
        
        # Remove explicitly excluded extensions
        if self.exclude_extensions:
            for ext in self.exclude_extensions:
                if not ext.startswith('.'):
                    ext = '.' + ext
                selected_extensions.discard(ext)
        
        return selected_extensions, selected_filenames


def run_cli_mode(cli_config: CLIConfig) -> int:
    """
    Run the application in CLI mode using the existing worker.
    
    Args:
        cli_config: CLI configuration object
        
    Returns:
        Exit code (0 for success, non-zero for errors)
    """
    try:
        # Configure logging for CLI mode
        configure_logging(
            verbose=cli_config.verbose,
            quiet=cli_config.quiet,
            log_level=cli_config.log_level,
            is_cli_mode=True
        )
        
        # Set up minimal QCoreApplication for CLI mode to support Qt-based worker
        app = QtCore.QCoreApplication(sys.argv)
        
        # Convert CLI config to worker configuration
        filter_settings = cli_config.to_filter_settings()
        generation_options = cli_config.to_generation_options()
        
        worker_config = WorkerConfig(
            filter_settings=filter_settings,
            generation_options=generation_options
        )
        
        # Create and configure the worker
        worker = GeneratorWorker(worker_config)
        
        # Create progress reporter
        progress_reporter = CLIProgressReporter(
            show_progress=cli_config.progress,
            quiet=cli_config.quiet
        )
        
        # Track completion state
        completion_state = {"finished": False, "temp_file": None, "error": None}
        
        def on_finished(temp_file: str, error_message: str):
            """Handle worker completion."""
            logging.debug(f"Worker finished - temp_file: {temp_file}, error: {error_message}")
            completion_state["finished"] = True
            completion_state["temp_file"] = temp_file
            completion_state["error"] = error_message
            app.quit()
        
        # Connect worker signals to progress reporter and completion handler
        worker.status_updated.connect(progress_reporter.on_status_updated)
        worker.progress_updated.connect(progress_reporter.on_progress_updated)
        worker.pre_count_finished.connect(progress_reporter.on_pre_count_finished)
        worker.finished.connect(on_finished)
        
        # Log configuration and limitations
        logging.info(f"Starting CLI processing of directory: {cli_config.directory}")
        logging.debug(f"Filter settings: {filter_settings}")
        logging.debug(f"Generation options: {generation_options}")
        
        # Warn about unsupported options due to current architecture limitations
        if not cli_config.recursive:
            logging.warning("--no-recursive option is not fully supported in current implementation. Processing will still be recursive.")
        
        if cli_config.include_hidden:
            logging.warning("--include-hidden option is not fully supported in current implementation. Hidden files will still be excluded.")
        
        # Use QTimer to start worker in the next event loop iteration
        QtCore.QTimer.singleShot(0, worker.run)
        
        # Run the event loop until worker completes
        app.exec()
        
        # Handle completion
        if completion_state["error"]:
            logging.error(f"Processing failed: {completion_state['error']}")
            return 4  # Processing error exit code
        
        if not completion_state["temp_file"]:
            logging.error("No output file generated")
            return 4  # Processing error exit code
        
        # Move temporary file to specified output location
        try:
            # Check if output file already exists and handle overwrite
            if cli_config.output_file.exists() and not cli_config.overwrite:
                logging.error(f"Output file already exists: {cli_config.output_file}")
                logging.error("Use --overwrite flag to overwrite existing files")
                # Clean up temp file
                temp_path = Path(completion_state["temp_file"])
                if temp_path.exists():
                    temp_path.unlink()
                return 5  # Output file error exit code
            
            # Ensure output directory exists
            cli_config.output_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Move temp file to final location
            shutil.move(completion_state["temp_file"], cli_config.output_file)
            
            logging.info(f"Output written to: {cli_config.output_file}")
            
            # Print summary statistics using progress reporter
            progress_reporter.print_summary(cli_config.output_file)
            
            return 0  # Success
            
        except OSError as e:
            logging.error(f"Failed to write output file: {e}")
            # Clean up temp file
            temp_path = Path(completion_state["temp_file"])
            if temp_path.exists():
                temp_path.unlink()
            return 5  # Output file error exit code
        
    except KeyboardInterrupt:
        logging.info("Operation cancelled by user")
        return 130  # Standard exit code for SIGINT
    except Exception as e:
        logging.error(f"Unexpected error in CLI mode: {e}", exc_info=True)
        return 1  # General error exit code


def parse_cli_arguments() -> Optional[argparse.Namespace]:
    """
    Parse command-line arguments.
    
    Returns:
        Parsed arguments namespace if CLI arguments are provided, None otherwise.
    """
    parser = argparse.ArgumentParser(
        prog="source-stitcher",
        description="Source Stitcher - Concatenate source code files into a single document",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                           # Launch GUI mode
  %(prog)s /path/to/project          # Launch GUI with pre-selected directory
  %(prog)s --cli /path/to/project --output result.md  # CLI mode
  %(prog)s --cli /path/to/project --output result.md --include-types python,javascript
  %(prog)s --cli /path/to/project --output result.md --exclude-extensions .pyc,.log
  %(prog)s --version                 # Show version information
  %(prog)s --list-types              # Show supported file types
  %(prog)s --help                    # Show this help message
        """,
    )
    
    # Positional argument for directory
    parser.add_argument(
        "directory",
        nargs="?",
        type=Path,
        help="Directory to process (optional for GUI mode, required for CLI mode)",
    )
    
    # CLI mode flag
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Run in CLI mode (non-interactive)",
    )
    
    # Output file for CLI mode
    parser.add_argument(
        "--output",
        type=Path,
        help="Output file path (required in CLI mode)",
    )
    
    # File type filtering options
    parser.add_argument(
        "--include-types",
        type=str,
        help="Comma-separated list of file types to include (e.g., 'python,javascript,web')",
    )
    
    parser.add_argument(
        "--exclude-types",
        type=str,
        help="Comma-separated list of file types to exclude (e.g., 'documentation,config')",
    )
    
    # Extension filtering options
    parser.add_argument(
        "--include-extensions",
        type=str,
        help="Comma-separated list of file extensions to include (e.g., '.py,.js,.ts')",
    )
    
    parser.add_argument(
        "--exclude-extensions",
        type=str,
        help="Comma-separated list of file extensions to exclude (e.g., '.pyc,.log,.tmp')",
    )
    
    # Ignore pattern options
    parser.add_argument(
        "--respect-gitignore",
        action="store_true",
        default=True,
        help="Respect .gitignore patterns (default behavior)",
    )
    
    parser.add_argument(
        "--no-gitignore",
        action="store_true",
        help="Ignore .gitignore patterns",
    )
    
    parser.add_argument(
        "--ignore-file",
        type=Path,
        help="Use specified ignore file instead of .gitignore",
    )
    
    # File selection options
    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help="Include hidden files and directories",
    )
    
    parser.add_argument(
        "--max-file-size",
        type=int,
        default=100,
        help="Maximum file size in MB to process (default: 100)",
    )
    
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Process directories recursively (default behavior)",
    )
    
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Only process files in the specified directory (not subdirectories)",
    )
    
    # Logging options
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output",
    )
    
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress all non-error output",
    )
    
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Set logging level (default: INFO)",
    )
    
    parser.add_argument(
        "--progress",
        action="store_true",
        help="Show progress information during processing",
    )
    
    # Output formatting options
    parser.add_argument(
        "--format",
        choices=["markdown", "plain", "json"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    
    parser.add_argument(
        "--encoding",
        default="utf-8",
        help="Output file encoding (default: utf-8)",
    )
    
    parser.add_argument(
        "--line-ending",
        choices=["unix", "windows", "mac"],
        default="unix",
        help="Line ending format (default: unix)",
    )
    
    parser.add_argument(
        "--no-stats",
        action="store_true",
        help="Exclude file statistics from output",
    )
    
    parser.add_argument(
        "--no-timestamp",
        action="store_true",
        help="Exclude timestamp from output",
    )
    
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output file without confirmation",
    )
    
    # Information commands
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {AppSettings().application_version}",
        help="Show version information and exit",
    )
    
    parser.add_argument(
        "--list-types",
        action="store_true",
        help="Show all supported file types and exit",
    )
    
    # Parse arguments
    args = parser.parse_args()
    
    # Handle --list-types command
    if args.list_types:
        language_extensions = get_language_extensions()
        print("Supported file types:")
        print("=" * 50)
        for lang_name, extensions in language_extensions.items():
            if lang_name == "Other Text Files":
                continue  # Skip the special category
            print(f"\n{lang_name}:")
            # Group extensions and filenames
            exts = [ext for ext in extensions if ext.startswith('.')]
            files = [ext for ext in extensions if not ext.startswith('.')]
            if exts:
                print(f"  Extensions: {', '.join(sorted(exts))}")
            if files:
                print(f"  Files: {', '.join(sorted(files))}")
        print(f"\nUse type names (case-insensitive) with --include-types or --exclude-types")
        print(f"Examples: 'python', 'javascript', 'web', 'config', 'documentation'")
        sys.exit(0)
    
    # Handle conflicting arguments
    if args.no_gitignore and args.ignore_file:
        parser.error("Cannot use both --no-gitignore and --ignore-file")
    
    if args.recursive and args.no_recursive:
        parser.error("Cannot use both --recursive and --no-recursive")
    
    if args.verbose and args.quiet:
        parser.error("Cannot use both --verbose and --quiet")
    
    # Basic validation for CLI mode
    if args.cli:
        if not args.directory:
            parser.error("Directory argument is required in CLI mode")
        if not args.output:
            parser.error("--output is required in CLI mode")
        if not args.directory.exists():
            parser.error(f"Directory does not exist: {args.directory}")
        if not args.directory.is_dir():
            parser.error(f"Path is not a directory: {args.directory}")
        if args.ignore_file and not args.ignore_file.exists():
            parser.error(f"Ignore file does not exist: {args.ignore_file}")
    
    # If no arguments provided (just the script name), return None to use GUI mode
    if len(sys.argv) == 1:
        return None
    
    return args


def main():
    """Main application entry point."""
    # Parse CLI arguments
    args = parse_cli_arguments()
    
    # Initialize application settings
    app_settings = AppSettings()

    QtCore.QCoreApplication.setApplicationName(app_settings.window_title)
    QtCore.QCoreApplication.setOrganizationName(app_settings.organization_name)
    QtCore.QCoreApplication.setApplicationVersion(app_settings.application_version)

    if args and args.cli:
        # CLI mode - create CLI config and run
        # Parse comma-separated lists
        include_types = []
        if args.include_types:
            include_types = [t.strip() for t in args.include_types.split(',') if t.strip()]
        
        exclude_types = []
        if args.exclude_types:
            exclude_types = [t.strip() for t in args.exclude_types.split(',') if t.strip()]
        
        include_extensions = []
        if args.include_extensions:
            include_extensions = [e.strip() for e in args.include_extensions.split(',') if e.strip()]
        
        exclude_extensions = []
        if args.exclude_extensions:
            exclude_extensions = [e.strip() for e in args.exclude_extensions.split(',') if e.strip()]
        
        # Determine gitignore behavior
        respect_gitignore = not args.no_gitignore
        
        # Determine recursive behavior (default is True)
        recursive = True
        if args.no_recursive:
            recursive = False
        elif args.recursive:
            recursive = True
        
        cli_config = CLIConfig(
            directory=args.directory,
            output_file=args.output,
            include_types=include_types,
            exclude_types=exclude_types,
            include_extensions=include_extensions,
            exclude_extensions=exclude_extensions,
            respect_gitignore=respect_gitignore,
            ignore_file=args.ignore_file,
            include_hidden=args.include_hidden,
            max_file_size_mb=args.max_file_size,
            recursive=recursive,
            verbose=args.verbose,
            quiet=args.quiet,
            log_level=args.log_level,
            progress=args.progress,
            output_format=args.format,
            encoding=args.encoding,
            line_ending=args.line_ending,
            include_stats=not args.no_stats,
            include_timestamp=not args.no_timestamp,
            overwrite=args.overwrite
        )
        exit_code = run_cli_mode(cli_config)
        sys.exit(exit_code)
    else:
        # GUI mode (existing functionality)
        app = QtWidgets.QApplication(sys.argv)

        settings = QtCore.QSettings(app_settings.organization_name, "SOTAConcatenator")
        
        # Check if directory was provided via CLI argument
        if args and args.directory:
            # Validate directory exists and is accessible
            if not args.directory.exists():
                QtWidgets.QMessageBox.critical(
                    None, "Error", f"Directory does not exist: {args.directory}"
                )
                sys.exit(1)
            if not args.directory.is_dir():
                QtWidgets.QMessageBox.critical(
                    None, "Error", f"Path is not a directory: {args.directory}"
                )
                sys.exit(1)
            
            # Use directory from CLI argument
            working_dir = args.directory
            settings.setValue("last_directory", str(working_dir))
        else:
            # Use existing directory selection dialog
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


if __name__ == "__main__":
    main()