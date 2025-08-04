"""File reading utilities with encoding detection and error handling."""

import logging
import time
from pathlib import Path
from typing import List, Optional

from ..file_utils import is_binary_file

logger = logging.getLogger(__name__)


class FileReader:
    """Handles reading files with multiple encoding fallbacks."""

    def __init__(
        self, encodings: Optional[List[str]] = None, default_encoding: str = "utf-8"
    ):
        """Initialize with encoding preferences."""
        self.encodings = encodings or [
            "utf-8",
            "utf-8-sig",
            "latin-1",
            "iso-8859-1",
            "cp1252",
            "ascii",
        ]
        self.default_encoding = default_encoding

    def get_file_content(self, filepath: Path) -> Optional[str]:
        """
        Safely read the content of a non-binary text file, trying multiple encodings.
        Returns None if the file is binary, cannot be read, or causes decoding errors.
        Catches MemoryError and falls back to chunked reading.
        """
        try:
            file_size = filepath.stat().st_size
        except (FileNotFoundError, PermissionError) as e:
            logger.warning(f"Could not stat file {filepath.name}: {e}")
            file_size = 0

        logger.info(f"Processing file: {filepath.name}")
        logger.debug(f"Attempting to read file: {filepath.name} ({file_size} bytes)")

        if is_binary_file(filepath):
            logger.info(f"Skipping binary file: {filepath.name}")
            return None

        last_error = None

        for encoding in self.encodings:
            logger.debug(f"Trying encoding: {encoding}")
            try:
                start_time = time.time()
                try:
                    content = filepath.read_text(encoding=encoding, errors="strict")
                except MemoryError:
                    logger.info(
                        f"Fallback to chunked reading for large file: {filepath.name}"
                    )
                    content = ""
                    with filepath.open("r", encoding=encoding, errors="strict") as f:
                        for chunk in iter(lambda: f.read(1024 * 1024), ""):
                            content += chunk

                read_time = time.time() - start_time
                logger.debug(
                    f"Successfully decoded with {encoding} in {read_time:.3f}s"
                )

                if not content.strip():
                    logger.info(f"Skipping empty file: {filepath.name}")
                    return None

                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(f"File content preview: {content[:100]}...")

                return content

            except UnicodeDecodeError as e:
                last_error = f"Failed to decode with {encoding}: {e}"
                logger.debug(f"Encoding {encoding} failed for {filepath.name}: {e}")
                continue

            except (PermissionError, FileNotFoundError, OSError) as e:
                logger.warning(f"Error reading {filepath.name}: {e}")
                return None

        logger.warning(
            f"Skipping file {filepath.name} - could not decode with any encoding. "
            f"Last error: {last_error}"
        )
        return None
