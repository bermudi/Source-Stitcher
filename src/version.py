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
        Version string from pyproject.toml.
        
    Raises:
        RuntimeError: If version cannot be determined from pyproject.toml.
    """
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
            raise RuntimeError("pyproject.toml not found in project directory tree")
        
        if tomllib is None:
            raise RuntimeError("tomllib not available - install tomli for Python < 3.11")
        
        # Read and parse pyproject.toml
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
        
        version = data.get("project", {}).get("version")
        if version:
            logging.debug(f"Version loaded from pyproject.toml: {version}")
            return version
        else:
            raise RuntimeError("Version not found in pyproject.toml [project] section")
            
    except Exception as e:
        if isinstance(e, RuntimeError):
            raise
        raise RuntimeError(f"Error reading version from pyproject.toml: {e}")


def get_app_name() -> str:
    """
    Get the application name from pyproject.toml.
    
    Returns:
        Application name from pyproject.toml.
        
    Raises:
        RuntimeError: If app name cannot be determined from pyproject.toml.
    """
    try:
        # Find pyproject.toml
        current_path = Path(__file__).parent
        pyproject_path = None
        
        for path in [current_path, current_path.parent, current_path.parent.parent]:
            potential_path = path / "pyproject.toml"
            if potential_path.exists():
                pyproject_path = potential_path
                break
        
        if not pyproject_path:
            raise RuntimeError("pyproject.toml not found in project directory tree")
            
        if tomllib is None:
            raise RuntimeError("tomllib not available - install tomli for Python < 3.11")
        
        # Read and parse pyproject.toml
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
        
        name = data.get("project", {}).get("name", "")
        if name:
            return name.replace("-", " ").title()
        else:
            raise RuntimeError("Name not found in pyproject.toml [project] section")
            
    except Exception as e:
        if isinstance(e, RuntimeError):
            raise
        raise RuntimeError(f"Error reading app name from pyproject.toml: {e}")


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