"""File utility functions for the Source Stitcher application."""

import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Set, Tuple
import pathspec

logger = logging.getLogger(__name__)


def load_ignore_patterns(
    directory: Path,
    use_gitignore: bool = True,
    use_npmignore: bool = False,
    use_dockerignore: bool = False,
) -> pathspec.PathSpec | None:
    """Loads ignore patterns from specified ignore files in the directory."""
    logger.debug(f"Loading ignore patterns from: {directory}")
    patterns = []
    ignore_files = []

    # Only add files that are enabled
    if use_gitignore:
        ignore_files.append(".gitignore")
    if use_npmignore:
        ignore_files.append(".npmignore")
    if use_dockerignore:
        ignore_files.append(".dockerignore")

    for ig_file in ignore_files:
        ignore_path = directory / ig_file
        if ignore_path.is_file():
            try:
                with ignore_path.open("r", encoding="utf-8", errors="ignore") as f:
                    patterns.extend(f.readlines())
            except Exception as e:
                logger.warning(f"Could not read {ignore_path}: {e}")

    git_dir = directory / ".git"
    if git_dir.is_dir():
        exclude_path = git_dir / "info" / "exclude"
        if exclude_path.is_file():
            try:
                with exclude_path.open("r", encoding="utf-8", errors="ignore") as f:
                    patterns.extend(f.readlines())
            except Exception as e:
                logger.warning(f"Could not read {exclude_path}: {e}")

    if patterns:
        try:
            return pathspec.PathSpec.from_lines(
                pathspec.patterns.GitWildMatchPattern, patterns
            )
        except Exception as e:
            logger.error(f"Error parsing ignore patterns from {directory}: {e}")
            return None
    return None


def load_global_gitignore() -> pathspec.PathSpec | None:
    """Load global gitignore patterns."""
    logger.debug("Loading global gitignore patterns")
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
        logger.warning(f"Could not load global gitignore: {e}")

    return (
        pathspec.PathSpec.from_lines(
            pathspec.patterns.GitWildMatchPattern, global_patterns
        )
        if global_patterns
        else None
    )


def is_binary_file(filepath: Path) -> bool:
    """Check if a file is likely binary by looking for null bytes."""
    logger.debug(f"Checking if file is binary: {filepath}")
    CHUNK_SIZE = 1024
    try:
        with filepath.open("rb") as f:
            chunk = f.read(CHUNK_SIZE)
        return b"\0" in chunk
    except OSError as e:
        logger.warning(
            f"Could not read start of file {filepath} to check if binary: {e}"
        )
        return True
    except Exception as e:
        logger.error(
            f"Unexpected error checking if file is binary {filepath}: {e}",
            exc_info=True,
        )
        return True


def is_likely_text_file(filepath: Path) -> bool:
    """
    Detect if file is likely text based on name patterns and content.
    """
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

    if filepath.name.lower() in text_filenames:
        return not is_binary_file(filepath)

    if filepath.name.startswith(".") and len(filepath.name) > 1:
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

    if not filepath.suffix:
        return not is_binary_file(filepath)

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

    # Only log the full configuration once
    if not hasattr(matches_file_type, "_logged_config"):
        logger.debug("File type matching configuration:")
        logger.debug(f"  - Selected extensions: {selected_exts}")
        logger.debug(f"  - Selected names: {selected_names}")
        logger.debug(f"  - Handle other files: {handle_other}")
        matches_file_type._logged_config = True

    matches = False
    reason = ""

    if file_name in selected_names:
        matches = True
        reason = f"file name matches selected name pattern"
    elif file_ext in selected_exts:
        matches = True
        reason = f"file extension matches selected patterns"
    elif handle_other and file_name not in all_names and file_ext not in all_exts:
        is_text = is_likely_text_file(filepath)
        matches = is_text
        reason = f"file is {'a text' if is_text else 'not a text'} file (other files handling enabled)"
    else:
        reason = "no matching criteria met"
        if not handle_other:
            reason += " (other files handling is disabled)"
        if file_name in all_names:
            reason += " (file name is a known type but not selected)"
        if file_ext in all_exts:
            reason += " (file extension is a known type but not selected)"

    logger.debug(f"File: {filepath.name} - {reason} - result: {matches}")
    return matches
