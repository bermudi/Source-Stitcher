#!/usr/bin/env python3
"""
Source Stitcher - Legacy entry point (now imports from modular structure).
For new development, use main.py instead.
"""

import logging
import sys
from pathlib import Path

from PyQt6 import QtCore, QtWidgets

from .config import AppSettings
from .main_window import FileConcatenator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def main():
    """Main application entry point."""
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


if __name__ == "__main__":
    main()