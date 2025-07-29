"""File reading utilities with encoding detection and error handling."""

import logging
from pathlib import Path
from typing import List, Optional

from ..file_utils import is_binary_file


class FileReader:
    """Handles reading files with multiple encoding fallbacks."""
    
    def __init__(self, encodings: Optional[List[str]] = None, default_encoding: str = "utf-8"):
        """Initialize with encoding preferences."""
        self.encodings = encodings or [
            "utf-8",  # Most common encoding for modern text files
            "utf-8-sig",  # UTF-8 with BOM
            "latin-1",  # Also known as ISO-8859-1, common in Western Europe
            "iso-8859-1",  # ISO Latin 1
            "cp1252",  # Windows-1252, common on Windows systems
            "ascii",  # Basic ASCII
        ]
        self.default_encoding = default_encoding

    def get_file_content(self, filepath: Path) -> Optional[str]:
        """
        Safely read the content of a non-binary text file, trying multiple encodings.
        Returns None if the file is binary, cannot be read, or causes decoding errors.
        Catches MemoryError and falls back to chunked reading.
        """
        if is_binary_file(filepath):
            logging.warning(
                f"Skipping binary file detected during read: {filepath.name}"
            )
            return None

        # Track the last exception for better error reporting
        last_error = None

        for encoding in self.encodings:
            try:
                try:
                    # Try reading the file with the current encoding
                    content = filepath.read_text(encoding=encoding, errors="strict")
                except MemoryError:
                    logging.warning(
                        f"MemoryError reading {filepath}, falling back to chunked read with {encoding}."
                    )
                    content = ""
                    with filepath.open("r", encoding=encoding, errors="strict") as f:
                        for chunk in iter(lambda: f.read(1024 * 1024), ""):
                            content += chunk

                # If we get here, the file was successfully read with this encoding
                if not content.strip():  # Skip empty or whitespace-only files
                    logging.info(f"Skipping empty file: {filepath.name}")
                    return None

                # Log which encoding worked for this file
                if encoding.lower() != "utf-8":
                    logging.info(
                        f"Successfully read {filepath.name} with {encoding} encoding"
                    )

                return content

            except UnicodeDecodeError as e:
                last_error = f"Failed to decode with {encoding}: {e}"
                continue  # Try the next encoding

            except (PermissionError, FileNotFoundError, OSError) as e:
                # These errors are not encoding-related, so we can stop trying
                logging.warning(f"Error reading {filepath.name}: {e}")
                return None

        # If we get here, all encodings failed
        logging.warning(
            f"Skipping file {filepath.name} - could not decode with any encoding. "
            f"Last error: {last_error}"
        )
        return None