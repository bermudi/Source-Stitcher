"""File utility functions for the Source Stitcher application."""

import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Set, Tuple
import pathspec


def load_ignore_patterns(directory: Path) -> pathspec.PathSpec | None:
    """Loads ignore patterns from various ignore files in the specified directory."""
    patterns = []
    ignore_files = [".gitignore", ".npmignore", ".dockerignore"]
    for ig_file in ignore_files:
        ignore_path = directory / ig_file
        if ignore_path.is_file():
            try:
                with ignore_path.open("r", encoding="utf-8", errors="ignore") as f:
                    patterns.extend(f.readlines())
            except Exception as e:
                logging.warning(f"Could not read {ignore_path}: {e}")

    # Also load .git/info/exclude if .git exists
    git_dir = directory / ".git"
    if git_dir.is_dir():
        exclude_path = git_dir / "info" / "exclude"
        if exclude_path.is_file():
            try:
                with exclude_path.open("r", encoding="utf-8", errors="ignore") as f:
                    patterns.extend(f.readlines())
            except Exception as e:
                logging.warning(f"Could not read {exclude_path}: {e}")

    if patterns:
        try:
            return pathspec.PathSpec.from_lines(
                pathspec.patterns.GitWildMatchPattern, patterns  # type: ignore[attr-defined]
            )
        except Exception as e:
            logging.error(f"Error parsing ignore patterns from {directory}: {e}")
            return None
    return None


def load_global_gitignore() -> pathspec.PathSpec | None:
    """Load global gitignore patterns."""
    global_patterns = []
    try:
        global_ignore = (
            subprocess.check_output(["git", "config", "--get", "core.excludesFile"])
            .decode()
            .strip()
        )
        global_path = Path(global_ignore).expanduser()
        if global_path.is_file():
            with global_path.open("r", encoding="utf-8", errors="ignore") as f:
                global_patterns = f.readlines()
    except Exception as e:
        logging.warning(f"Could not load global gitignore: {e}")
    
    return (
        pathspec.PathSpec.from_lines(
            pathspec.patterns.GitWildMatchPattern, global_patterns
        )
        if global_patterns
        else None
    )


def is_binary_file(filepath: Path) -> bool:
    """Check if a file is likely binary by looking for null bytes."""
    CHUNK_SIZE = 1024
    try:
        with filepath.open("rb") as f:
            chunk = f.read(CHUNK_SIZE)
        return b"\0" in chunk
    except OSError as e:
        logging.warning(
            f"Could not read start of file {filepath} to check if binary: {e}"
        )
        return True
    except Exception as e:
        logging.error(
            f"Unexpected error checking if file is binary {filepath}: {e}",
            exc_info=True,
        )
        return True


def is_likely_text_file(filepath: Path) -> bool:
    """
    Detect if file is likely text based on name patterns and content.
    """
    # Known text filenames without extensions
    text_filenames = {
        "readme",
        "license",
        "licence",
        "changelog",
        "changes",
        "authors",
        "contributors",
        "copying",
        "install",
        "news",
        "todo",
        "version",
        "dockerfile",
        "makefile",
        "rakefile",
        "gemfile",
        "pipfile",
        "procfile",
        "vagrantfile",
        "jenkinsfile",
        "cname",
        "notice",
        "manifest",
        "copyright",
    }

    # Check if it's a known text filename (case insensitive)
    if filepath.name.lower() in text_filenames:
        return not is_binary_file(filepath)

    # Dotfiles are often config files (but skip .git, .DS_Store, etc.)
    if filepath.name.startswith(".") and len(filepath.name) > 1:
        # Skip known binary or special dotfiles
        skip_dotfiles = {
            ".git",
            ".ds_store",
            ".pyc",
            ".pyo",
            ".pyd",
            ".so",
            ".dylib",
            ".dll",
        }
        if filepath.name.lower() not in skip_dotfiles:
            return not is_binary_file(filepath)

    # Files with no extension that aren't binary
    if not filepath.suffix:
        return not is_binary_file(filepath)

    # Files with unusual extensions that might be text
    possible_text_extensions = {
        ".ini",
        ".cfg",
        ".conf",
        ".config",
        ".properties",
        ".env",
        ".envrc",
        ".ignore",
        ".keep",
        ".gitkeep",
        ".npmignore",
        ".dockerignore",
        ".editorconfig",
        ".flake8",
        ".pylintrc",
        ".prettierrc",
        ".eslintrc",
        ".stylelintrc",
        ".babelrc",
        ".npmrc",
        ".yarnrc",
        ".nvmrc",
        ".ruby-version",
        ".python-version",
        ".node-version",
        ".terraform",
        ".tf",
        ".tfvars",
        ".ansible",
        ".playbook",
        ".vault",
        ".j2",
        ".jinja",
        ".jinja2",
        ".template",
        ".tmpl",
        ".tpl",
        ".mustache",
        ".hbs",
        ".handlebars",
    }

    if filepath.suffix.lower() in possible_text_extensions:
        return not is_binary_file(filepath)

    return False


def build_filter_sets(ext_dict: Dict[str, List[str]]) -> Tuple[Set[str], Set[str]]:
    """Compiles all known extensions and filenames into sets for quick lookup."""
    by_ext: Set[str] = set()
    by_name: Set[str] = set()
    for exts in ext_dict.values():
        for e in exts:
            (by_ext if e.startswith(".") else by_name).add(e.lower())
    return by_ext, by_name


def matches_file_type(
    filepath: Path,
    selected_exts: Set[str],
    selected_names: Set[str],
    all_exts: Set[str],
    all_names: Set[str],
    handle_other: bool,
) -> bool:
    """Check if a file path matches the compiled filter sets."""
    file_ext = filepath.suffix.lower()
    file_name = filepath.name.lower()

    if file_name in selected_names:
        return True
    if file_ext in selected_exts:
        return True

    # Handle "Other Text Files" logic
    if handle_other:
        # Check if the file does NOT match any of the known file types
        if file_name not in all_names and file_ext not in all_exts:
            return is_likely_text_file(filepath)

    return False