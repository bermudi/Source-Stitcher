#!/usr/bin/env python3
"""
Main entry point for the Source Stitcher application.
"""

import logging
import sys
from pathlib import Path

from PyQt6 import QtCore, QtWidgets

from src.config import AppSettings
from src.main_window import FileConcatenator
from src.logging_config import configure_logging
from src.cli.parser import parse_cli_arguments, create_cli_config_from_args
from src.cli.runner import run_cli_mode

# Default logging configuration - will be reconfigured based on CLI args
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


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
        cli_config = create_cli_config_from_args(args)
        configure_logging(
            verbose=cli_config.verbose,
            quiet=cli_config.quiet,
            log_level=cli_config.log_level,
            is_cli_mode=True
        )
        exit_code = run_cli_mode(cli_config)
        sys.exit(exit_code)
    else:
        # GUI mode
        # Configure logging for GUI mode - use CLI args if provided
        verbose = args.verbose if args else False
        quiet = args.quiet if args else False
        log_level = args.log_level if args else "INFO"
        
        configure_logging(
            verbose=verbose,
            quiet=quiet,
            log_level=log_level,
            is_cli_mode=False
        )
        
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