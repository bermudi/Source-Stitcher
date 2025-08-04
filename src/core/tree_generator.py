"""Tree structure generation for displaying selected files."""

import logging
from pathlib import Path
from typing import Dict, List, Set

logger = logging.getLogger(__name__)


class ProjectTreeGenerator:
    """Generates ASCII tree representation of selected files."""

    def __init__(self, base_directory: Path):
        """Initialize the tree generator.

        Args:
            base_directory: Base directory for making paths relative
        """
        self.base_directory = base_directory

    def generate_tree(self, file_paths: List[Path]) -> str:
        """Generate ASCII tree representation of the given file paths.

        Args:
            file_paths: List of Path objects to include in the tree

        Returns:
            String containing the ASCII tree representation
        """
        if not file_paths:
            return ""

        # Convert absolute paths to relative and sort
        relative_paths = []
        seen_paths: Set[str] = set()

        for path in sorted(file_paths, key=lambda p: str(p).lower()):
            try:
                rel_path = path.relative_to(self.base_directory)
                path_str = str(rel_path)
                if path_str not in seen_paths:
                    relative_paths.append(rel_path)
                    seen_paths.add(path_str)
            except ValueError:
                logger.warning(f"Could not make path relative: {path}")
                continue

        if not relative_paths:
            return ""

        # Build directory structure
        structure = self._build_directory_structure(relative_paths)

        # Generate tree lines
        tree_lines = []
        base_name = self.base_directory.name or str(self.base_directory)
        tree_lines.append(f"{base_name}/")
        tree_lines.extend(self._render_ascii_tree(structure))

        return "\n".join(tree_lines)

    def _build_directory_structure(self, relative_paths: List[Path]) -> Dict:
        """Build nested dictionary representing directory structure.

        Args:
            relative_paths: List of relative Path objects

        Returns:
            Nested dictionary with directory structure
        """
        structure: Dict = {}

        for path in relative_paths:
            current = structure
            parts = path.parts

            # Build nested structure
            for i, part in enumerate(parts):
                is_last = i == len(parts) - 1

                if is_last:
                    current[part] = None  # Files are leaf nodes
                else:
                    if part not in current:
                        current[part] = {}
                    current = current[part]

        return structure

    def _render_ascii_tree(
        self, structure: Dict, prefix: str = "", is_last: bool = True
    ) -> List[str]:
        """Recursively render ASCII tree lines.

        Args:
            structure: Nested dictionary of directory structure
            prefix: Current line prefix for proper indentation
            is_last: Whether current item is last in its group

        Returns:
            List of formatted tree lines
        """
        lines = []

        if not structure:
            return lines

        # Sort items - directories (dict values) first, then files (None values)
        items = sorted(structure.items(), key=lambda x: (x[1] is None, x[0].lower()))

        for i, (name, subtree) in enumerate(items):
            is_last_item = i == len(items) - 1

            # Add connector and item name
            if is_last_item:
                connector = "└── "
                child_prefix = prefix + "    "
            else:
                connector = "├── "
                child_prefix = prefix + "│   "

            lines.append(f"{prefix}{connector}{name}")

            # Recursively process subdirectories
            if isinstance(subtree, dict):
                lines.extend(
                    self._render_ascii_tree(subtree, child_prefix, is_last_item)
                )

        return lines
