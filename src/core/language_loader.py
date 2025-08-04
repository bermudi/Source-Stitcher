"""Language definition loader for external TOML configuration."""

import logging

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # Python < 3.11
from pathlib import Path
from typing import Dict, List, Set, Optional, Union

logger = logging.getLogger(__name__)


class LanguageDefinitionLoader:
    """
    Loads language definitions from TOML configuration files.

    Single source of truth: TOML.
    If the TOML file is missing or invalid, we create a default TOML file
    (derived from a minimal built-in seed) and then load from it.
    """

    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize the language definition loader.

        Args:
            config_path: Optional path to TOML configuration file.
                        If None, will look for 'language_definitions.toml' in current directory.
        """
        self.config_path = config_path or Path("language_definitions.toml")
        self._definitions: Optional[Dict[str, Dict[str, Union[List[str], str]]]] = None
        logger.debug(
            f"LanguageDefinitionLoader initialized with config path: {self.config_path}"
        )

    def load_definitions(self) -> Dict[str, List[str]]:
        """
        Load language definitions from TOML file.

        Returns:
            Dictionary mapping language names to lists of extensions/filenames
        """
        if self._definitions is None:
            data = self._load_from_toml()
            if data is None:
                logger.warning(
                    "Language TOML missing or invalid. Creating default file."
                )
                # Create default file then attempt to load again
                self.create_default_toml_file(self.config_path)
                data = self._load_from_toml()
                if data is None:
                    # As a last resort, use a tiny built-in seed to keep app functional
                    logger.error(
                        "Failed to load language definitions after creating default TOML. Using built-in minimal seed."
                    )
                    data = self._get_minimal_seed_definitions()

            self._definitions = data

        # Convert TOML structure to the expected format
        result: Dict[str, List[str]] = {}
        for lang_name, lang_data in self._definitions.items():
            extensions = list(lang_data.get("extensions", []))  # type: ignore[assignment]
            filenames = list(lang_data.get("filenames", []))  # type: ignore[assignment]
            result[lang_name] = extensions + filenames

        logger.debug(f"Loaded definitions for {len(result)} languages")
        return result

    def _load_from_toml(self) -> Optional[Dict[str, Dict[str, Union[List[str], str]]]]:
        """
        Load language definitions from TOML file.

        Returns:
            Dictionary of language definitions or None if loading failed
        """
        if not self.config_path.exists():
            logger.info(f"TOML config file not found: {self.config_path}")
            return None

        try:
            with open(self.config_path, "rb") as f:
                data = tomllib.load(f)

            logger.info(
                f"Successfully loaded language definitions from {self.config_path}"
            )
            return data

        except Exception as e:
            logger.error(f"Error loading TOML config from {self.config_path}: {e}")
            return None

    def _get_minimal_seed_definitions(
        self,
    ) -> Dict[str, Dict[str, Union[List[str], str]]]:
        """
        Provide a minimal built-in seed of definitions to keep the app operational
        if TOML cannot be loaded or created for any reason.
        """
        return {
            "Python": {
                "extensions": [".py"],
                "filenames": ["pyproject.toml", "requirements.txt"],
                "description": "Python source files and configuration",
            },
            "Other Text Files": {
                "extensions": [],
                "filenames": ["*other*"],
                "description": "Other text files",
            },
        }

    def get_all_extensions(self) -> Set[str]:
        """
        Get all known file extensions from loaded definitions.

        Returns:
            Set of all file extensions (including the dot)
        """
        definitions = self.load_definitions()
        extensions = set()

        for items in definitions.values():
            for item in items:
                if item.startswith("."):
                    extensions.add(item)

        logger.debug(f"Found {len(extensions)} unique extensions")
        return extensions

    def get_all_filenames(self) -> Set[str]:
        """
        Get all known special filenames from loaded definitions.

        Returns:
            Set of all special filenames (without extensions)
        """
        definitions = self.load_definitions()
        filenames = set()

        for items in definitions.values():
            for item in items:
                if not item.startswith(".") and item != "*other*":
                    filenames.add(
                        item.lower()
                    )  # Store in lowercase for case-insensitive matching

        logger.debug(f"Found {len(filenames)} unique filenames")
        return filenames

    def get_language_for_file(self, file_path: Path) -> Optional[str]:
        """
        Determine which language category a file belongs to.

        Args:
            file_path: Path to the file

        Returns:
            Language name or None if no match found
        """
        definitions = self.load_definitions()
        file_ext = file_path.suffix.lower()
        file_name = file_path.name.lower()

        for lang_name, items in definitions.items():
            for item in items:
                if item.startswith(".") and item.lower() == file_ext:
                    return lang_name
                elif (
                    not item.startswith(".")
                    and item != "*other*"
                    and item.lower() == file_name
                ):
                    return lang_name

        return None

    def create_default_toml_file(self, output_path: Optional[Path] = None) -> Path:
        """
        Create a default TOML configuration file with current language definitions.

        Args:
            output_path: Optional path for the output file.
                        If None, uses self.config_path.

        Returns:
            Path to the created TOML file
        """
        output_path = output_path or self.config_path

        # Use a rich default by reading existing TOML if present; otherwise seed with minimal defaults
        existing = self._load_from_toml()
        definitions = (
            existing if existing is not None else self._get_minimal_seed_definitions()
        )

        # Create TOML content
        toml_content = [
            "# Source-Stitcher Language Definitions",
            "# Users can customize this file to add or modify supported file types",
            "# Each language section can have 'extensions', 'filenames', and 'description' fields",
            "",
        ]

        for lang_name, lang_data in definitions.items():
            # Clean up language name for TOML section
            section_name = (
                lang_name.replace("/", "_").replace(" ", "_").replace("-", "_")
            )
            toml_content.append(f"[{section_name}]")

            if lang_data.get("extensions"):
                ext_list = ", ".join(f'"{ext}"' for ext in lang_data["extensions"])
                toml_content.append(f"extensions = [{ext_list}]")

            if lang_data.get("filenames"):
                filename_list = ", ".join(
                    f'"{name}"' for name in lang_data["filenames"]
                )
                toml_content.append(f"filenames = [{filename_list}]")

            if lang_data.get("description"):
                toml_content.append(f'description = "{lang_data["description"]}"')

            toml_content.append("")

        # Write to file
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(toml_content))

        logger.info(f"Created default TOML configuration file: {output_path}")
        return output_path
