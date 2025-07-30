"""Version management utilities."""

import logging
from pathlib import Path
from typing import Optional

try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # Fallback for older Python versions
    except ImportError:
        tomllib = None


def get_version() -> str:
    """
    Get the application version from pyproject.toml.
    
    Returns:
        Version string from pyproject.toml, or fallback version if unable to read.
    """
    fallback_version = "1.5-tree"  # Keep as fallback for development
    
    try:
        # Find pyproject.toml - look in current directory and parent directories
        current_path = Path(__file__).parent
        pyproject_path = None
        
        # Search up the directory tree for pyproject.toml
        for path in [current_path, current_path.parent, current_path.parent.parent]:
            potential_path = path / "pyproject.toml"
            if potential_path.exists():
                pyproject_path = potential_path
                break
        
        if not pyproject_path:
            logging.debug("pyproject.toml not found, using fallback version")
            return fallback_version
        
        if tomllib is None:
            logging.debug("tomllib not available, using fallback version")
            return fallback_version
        
        # Read and parse pyproject.toml
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
        
        version = data.get("project", {}).get("version")
        if version:
            logging.debug(f"Version loaded from pyproject.toml: {version}")
            return version
        else:
            logging.debug("Version not found in pyproject.toml, using fallback")
            return fallback_version
            
    except Exception as e:
        logging.debug(f"Error reading version from pyproject.toml: {e}, using fallback")
        return fallback_version


def get_app_name() -> str:
    """
    Get the application name from pyproject.toml.
    
    Returns:
        Application name from pyproject.toml, or fallback name if unable to read.
    """
    fallback_name = "Source Stitcher"
    
    try:
        # Find pyproject.toml
        current_path = Path(__file__).parent
        pyproject_path = None
        
        for path in [current_path, current_path.parent, current_path.parent.parent]:
            potential_path = path / "pyproject.toml"
            if potential_path.exists():
                pyproject_path = potential_path
                break
        
        if not pyproject_path or tomllib is None:
            return fallback_name
        
        # Read and parse pyproject.toml
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
        
        name = data.get("project", {}).get("name", "").replace("-", " ").title()
        return name if name else fallback_name
            
    except Exception:
        return fallback_name


# Cache the version to avoid repeated file reads
_cached_version: Optional[str] = None
_cached_app_name: Optional[str] = None


def get_cached_version() -> str:
    """Get version with caching for performance."""
    global _cached_version
    if _cached_version is None:
        _cached_version = get_version()
    return _cached_version


def get_cached_app_name() -> str:
    """Get app name with caching for performance."""
    global _cached_app_name
    if _cached_app_name is None:
        _cached_app_name = get_app_name()
    return _cached_app_name