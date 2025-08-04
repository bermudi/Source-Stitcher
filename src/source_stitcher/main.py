#!/usr/bin/env python3
"""
Main entry point for the Source Stitcher application.
"""

import logging
import sys
from pathlib import Path

from PyQt6 import QtCore, QtWidgets

from source_stitcher.config import AppSettings
from source_stitcher.ui.main_window import FileConcatenator
from source_stitcher.logging_config import configure_logging
from source_stitcher.cli.parser import parse_cli_arguments, create_cli_config_from_args
from source_stitcher.cli.runner import run_cli_mode

# Default logging configuration - will be reconfigured based on CLI args
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)


def main():
    """Main application entry point."""
    logger.debug("Application starting.")
    args = parse_cli_arguments()
    app_settings = AppSettings()

    QtCore.QCoreApplication.setApplicationName(app_settings.window_title)
    QtCore.QCoreApplication.setOrganizationName(app_settings.organization_name)
    QtCore.QCoreApplication.setApplicationVersion(app_settings.application_version)

    if args and args.cli:
        logger.debug("Running in CLI mode.")
        cli_config = create_cli_config_from_args(args)
        configure_logging(
            verbose=cli_config.verbose,
            quiet=cli_config.quiet,
            log_level=cli_config.log_level,
            is_cli_mode=True,
        )
        exit_code = run_cli_mode(cli_config)
        sys.exit(exit_code)
    else:
        logger.debug("Running in GUI mode.")
        verbose = args.verbose if args else False
        quiet = args.quiet if args else False
        log_level = args.log_level if args else "INFO"

        configure_logging(
            verbose=verbose, quiet=quiet, log_level=log_level, is_cli_mode=False
        )

        app = QtWidgets.QApplication(sys.argv)
        settings = QtCore.QSettings(app_settings.organization_name, "SOTAConcatenator")

        if args and args.directory:
            logger.debug(f"Directory provided via CLI argument: {args.directory}")
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

            working_dir = args.directory
            settings.setValue("last_directory", str(working_dir))
        else:
            logger.debug("No directory provided via CLI, opening selection dialog.")
            last_dir = settings.value("last_directory", str(Path.cwd()))
            selected_dir = QtWidgets.QFileDialog.getExistingDirectory(
                None, "Select Project Directory To Concatenate", last_dir
            )

            if selected_dir:
                working_dir = Path(selected_dir)
                logger.info(f"User selected directory: {working_dir}")
                settings.setValue("last_directory", selected_dir)
            else:
                logger.warning("No directory selected on startup. Exiting.")
                sys.exit(0)

        window = FileConcatenator(working_dir=working_dir)
        window.show()
        sys.exit(app.exec())


if __name__ == "__main__":
    main()
