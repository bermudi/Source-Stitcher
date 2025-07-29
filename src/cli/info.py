"""Information display functions for CLI."""

from ..config import AppSettings
from ..language_definitions import get_language_extensions


def show_supported_file_types():
    """Display all supported file types with detailed information."""
    language_extensions = get_language_extensions()
    
    print("Source Stitcher - Supported File Types")
    print("=" * 60)
    print()
    
    # Calculate statistics
    total_categories = len([k for k in language_extensions.keys() if k != "Other Text Files"])
    total_extensions = sum(len([ext for ext in exts if ext.startswith('.')]) 
                          for exts in language_extensions.values())
    total_filenames = sum(len([ext for ext in exts if not ext.startswith('.')]) 
                         for exts in language_extensions.values())
    
    print(f"Total categories: {total_categories}")
    print(f"Total extensions: {total_extensions}")
    print(f"Total specific filenames: {total_filenames}")
    print()
    
    # Display each category
    for lang_name, extensions in language_extensions.items():
        if lang_name == "Other Text Files":
            continue  # Skip the special category
            
        print(f"{lang_name}:")
        print("-" * len(lang_name))
        
        # Group extensions and filenames
        exts = sorted([ext for ext in extensions if ext.startswith('.')])
        files = sorted([ext for ext in extensions if not ext.startswith('.')])
        
        if exts:
            # Format extensions in columns for better readability
            ext_str = ', '.join(exts)
            if len(ext_str) > 70:
                # Split into multiple lines if too long
                ext_lines = []
                current_line = "  Extensions: "
                for ext in exts:
                    if len(current_line + ext + ", ") > 75:
                        ext_lines.append(current_line.rstrip(", "))
                        current_line = "              " + ext + ", "
                    else:
                        current_line += ext + ", "
                ext_lines.append(current_line.rstrip(", "))
                print("\n".join(ext_lines))
            else:
                print(f"  Extensions: {ext_str}")
        
        if files:
            # Format filenames similarly
            files_str = ', '.join(files)
            if len(files_str) > 70:
                file_lines = []
                current_line = "  Files: "
                for file in files:
                    if len(current_line + file + ", ") > 75:
                        file_lines.append(current_line.rstrip(", "))
                        current_line = "         " + file + ", "
                    else:
                        current_line += file + ", "
                file_lines.append(current_line.rstrip(", "))
                print("\n".join(file_lines))
            else:
                print(f"  Files: {files_str}")
        
        print()
    
    # Usage examples
    print("Usage Examples:")
    print("=" * 15)
    print()
    print("Include specific types:")
    print("  --include-types python,javascript")
    print("  --include-types 'web frontend,config'")
    print()
    print("Exclude specific types:")
    print("  --exclude-types documentation,devops")
    print("  --exclude-types 'version control'")
    print()
    print("Mix with extensions:")
    print("  --include-types python --exclude-extensions .pyc,.pyo")
    print("  --include-extensions .py,.js --exclude-types documentation")
    print()
    print("Notes:")
    print("- Type names are case-insensitive and support partial matching")
    print("- Use quotes for type names containing spaces")
    print("- Extensions should include the dot (e.g., '.py' not 'py')")
    print("- Exclude filters take precedence over include filters")


def show_version_info():
    """Display detailed version information."""
    app_settings = AppSettings()
    print(f"Source Stitcher v{app_settings.application_version}")
    print()
    print("A tool for concatenating source code files into unified documents")
    print("Supports both GUI and CLI modes for flexible usage")
    print()
    print("For more information and usage examples, use --help")