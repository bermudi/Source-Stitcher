"""Logging configuration for both CLI and GUI modes."""

import logging
import sys


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