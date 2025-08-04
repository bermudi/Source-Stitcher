"""Command-line argument parsing and validation."""

import argparse
import sys
from pathlib import Path
from typing import Optional

from ..language_definitions import get_language_extensions
from .config import CLIConfig
from .info import show_supported_file_types, show_version_info


def show_helpful_error(
    parser: argparse.ArgumentParser, error_msg: str, suggestion: str = None
):
    """Display helpful error messages with usage hints."""
    print(f"Error: {error_msg}", file=sys.stderr)
    if suggestion:
        print(f"Suggestion: {suggestion}", file=sys.stderr)
    print(file=sys.stderr)
    print("For help, use: source-stitcher --help", file=sys.stderr)
    print(
        "For supported file types, use: source-stitcher --list-types", file=sys.stderr
    )
    print("For version information, use: source-stitcher --version", file=sys.stderr)
    sys.exit(2)


def parse_cli_arguments() -> Optional[argparse.Namespace]:
    """
    Parse command-line arguments.

    Returns:
        Parsed arguments namespace if CLI arguments are provided, None otherwise.
    """
    parser = argparse.ArgumentParser(
        prog="source-stitcher",
        description="""
Source Stitcher - Concatenate source code files into unified documents

A powerful tool for combining multiple source code files into a single document,
supporting both GUI and CLI modes. Perfect for code reviews, documentation
generation, and AI/LLM consumption of codebases.

Supports 15+ programming languages with intelligent file type detection,
gitignore pattern matching, and flexible filtering options.
        """.strip(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                    # Launch GUI mode
  %(prog)s /path/to/project                   # GUI with pre-selected directory
  %(prog)s --cli /project --output result.md # Basic CLI usage
  
  # File type filtering
  %(prog)s --cli /project --output code.md --include-types python,javascript
  %(prog)s --cli /project --output code.md --exclude-types documentation,config
  %(prog)s --cli /project --output code.md --include-extensions .py,.js,.ts
  
  # Output formatting
  %(prog)s --cli /project --output code.txt --format plain --no-stats
  %(prog)s --cli /project --output code.json --format json --encoding utf-16
  
  # Logging and progress
  %(prog)s --cli /project --output code.md --verbose --progress
  %(prog)s --cli /project --output code.md --quiet --overwrite
  
  # Information commands
  %(prog)s --version                          # Show version information
  %(prog)s --list-types                       # Show supported file types
  %(prog)s --help                             # Show this help message

For more detailed examples and usage patterns, visit the project documentation.
        """,
    )

    # Add all argument definitions
    _add_arguments(parser)

    # Parse arguments
    args = parser.parse_args()

    # Handle information commands
    if args.version:
        show_version_info()
        sys.exit(0)

    if args.list_types:
        show_supported_file_types()
        sys.exit(0)

    # Validate arguments
    _validate_arguments(parser, args)

    # If no arguments provided, return None for GUI mode
    if len(sys.argv) == 1:
        print("Source Stitcher - No arguments provided, launching GUI mode")
        print()
        print(
            "For CLI usage: source-stitcher --cli /path/to/project --output result.md"
        )
        print("For help: source-stitcher --help")
        print("For supported file types: source-stitcher --list-types")
        print()
        return None

    return args


def _add_arguments(parser: argparse.ArgumentParser):
    """Add all command-line arguments to the parser."""
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
        action="store_true",
        help="Show version information and exit",
    )

    parser.add_argument(
        "--list-types",
        action="store_true",
        help="Show all supported file types and exit",
    )


def _validate_arguments(parser: argparse.ArgumentParser, args: argparse.Namespace):
    """Validate parsed arguments and show helpful errors."""
    # Handle conflicting arguments with helpful messages
    if args.no_gitignore and args.ignore_file:
        show_helpful_error(
            parser,
            "Cannot use both --no-gitignore and --ignore-file",
            "Use either --no-gitignore to disable all ignore patterns, or --ignore-file to specify a custom ignore file",
        )

    if args.recursive and args.no_recursive:
        show_helpful_error(
            parser,
            "Cannot use both --recursive and --no-recursive",
            "Choose either --recursive (default) to process subdirectories, or --no-recursive to process only the specified directory",
        )

    if args.verbose and args.quiet:
        show_helpful_error(
            parser,
            "Cannot use both --verbose and --quiet",
            "Choose either --verbose for detailed output, or --quiet to suppress non-error messages",
        )

    # Validate file type arguments
    if args.include_types and args.exclude_types:
        # Check for overlapping types
        include_set = set(t.strip().lower() for t in args.include_types.split(","))
        exclude_set = set(t.strip().lower() for t in args.exclude_types.split(","))
        overlap = include_set.intersection(exclude_set)
        if overlap:
            show_helpful_error(
                parser,
                f"File types cannot be both included and excluded: {', '.join(overlap)}",
                "Remove overlapping types from either --include-types or --exclude-types",
            )

    # Basic validation for CLI mode
    if args.cli:
        _validate_cli_mode(parser, args)

    # Validate file type names if provided
    _validate_file_types(parser, args)


def _validate_cli_mode(parser: argparse.ArgumentParser, args: argparse.Namespace):
    """Validate CLI mode specific arguments."""
    if not args.directory:
        show_helpful_error(
            parser,
            "Directory argument is required in CLI mode",
            "Provide a directory path: source-stitcher --cli /path/to/project --output result.md",
        )
    if not args.output:
        show_helpful_error(
            parser,
            "--output is required in CLI mode",
            "Specify output file: source-stitcher --cli /path/to/project --output result.md",
        )
    if not args.directory.exists():
        show_helpful_error(
            parser,
            f"Directory does not exist: {args.directory}",
            "Check the directory path and ensure it exists",
        )
    if not args.directory.is_dir():
        show_helpful_error(
            parser,
            f"Path is not a directory: {args.directory}",
            "Provide a valid directory path, not a file",
        )
    if args.ignore_file and not args.ignore_file.exists():
        show_helpful_error(
            parser,
            f"Ignore file does not exist: {args.ignore_file}",
            "Check the ignore file path and ensure it exists",
        )

    # Validate output directory is writable
    output_dir = args.output.parent
    if not output_dir.exists():
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            show_helpful_error(
                parser,
                f"Cannot create output directory: {output_dir}",
                f"Check permissions and path validity: {e}",
            )
    elif not output_dir.is_dir():
        show_helpful_error(
            parser,
            f"Output path parent is not a directory: {output_dir}",
            "Ensure the output file path is valid",
        )


def _validate_file_types(parser: argparse.ArgumentParser, args: argparse.Namespace):
    """Validate file type names if provided."""
    if args.include_types or args.exclude_types:
        language_extensions = get_language_extensions()
        valid_types = [
            name.lower()
            for name in language_extensions.keys()
            if name != "Other Text Files"
        ]

        for type_arg, arg_name in [
            (args.include_types, "--include-types"),
            (args.exclude_types, "--exclude-types"),
        ]:
            if type_arg:
                provided_types = [t.strip().lower() for t in type_arg.split(",")]
                invalid_types = []
                for ptype in provided_types:
                    # Check for exact match or partial match
                    if not any(
                        ptype in vtype or vtype in ptype for vtype in valid_types
                    ):
                        invalid_types.append(ptype)

                if invalid_types:
                    show_helpful_error(
                        parser,
                        f"Unknown file types in {arg_name}: {', '.join(invalid_types)}",
                        "Use --list-types to see all supported file types",
                    )


def create_cli_config_from_args(args: argparse.Namespace) -> CLIConfig:
    """Create CLIConfig from parsed arguments."""
    # Parse comma-separated lists
    include_types = []
    if args.include_types:
        include_types = [t.strip() for t in args.include_types.split(",") if t.strip()]

    exclude_types = []
    if args.exclude_types:
        exclude_types = [t.strip() for t in args.exclude_types.split(",") if t.strip()]

    include_extensions = []
    if args.include_extensions:
        include_extensions = [
            e.strip() for e in args.include_extensions.split(",") if e.strip()
        ]

    exclude_extensions = []
    if args.exclude_extensions:
        exclude_extensions = [
            e.strip() for e in args.exclude_extensions.split(",") if e.strip()
        ]

    # Determine gitignore behavior
    respect_gitignore = not args.no_gitignore

    # Determine recursive behavior (default is True)
    recursive = True
    if args.no_recursive:
        recursive = False
    elif args.recursive:
        recursive = True

    return CLIConfig(
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
        overwrite=args.overwrite,
    )
