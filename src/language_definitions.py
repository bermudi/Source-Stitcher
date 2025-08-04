"""Language definitions dispatcher.

This module previously hardcoded the language/filename mappings.
To keep a single source of truth, it now delegates to the TOML-backed loader.
"""

from typing import Dict, List
from pathlib import Path
import logging

from .core.language_loader import LanguageDefinitionLoader

logger = logging.getLogger(__name__)


def get_language_extensions(config_path: Path | None = None) -> Dict[str, List[str]]:
    """
    Load language definitions from the TOML configuration via LanguageDefinitionLoader.

    Args:
        config_path: Optional explicit path to language_definitions.toml

    Returns:
        A mapping of language name -> list of extensions and filenames
    """
    loader = LanguageDefinitionLoader(config_path=config_path)
    return loader.load_definitions()
