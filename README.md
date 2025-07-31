# Source Stitcher

A PyQt6-based application for concatenating multiple source code files with intelligent filtering and language detection.


![Screenshot 1](https://i.postimg.cc/8CyDPymp/Screenshot-20250730-185558.png)

![Screenshot 2](https://i.postimg.cc/t40v75r9/Screenshot-20250728-152107.png)


## Project Structure


```
src/
├── __init__.py                 # Package initialization
├── source-stitcher.py         # Legacy entry point (wrapper)
├── config.py                  # Configuration dataclasses
├── file_utils.py              # File utility functions
├── language_definitions.py    # Language and file type definitions
├── worker.py                  # Background worker thread
├── main_window.py             # Main application window
├── core/                      # Core business logic
│   ├── __init__.py
│   ├── file_reader.py         # File reading with encoding detection
│   ├── file_counter.py        # File counting for progress
│   └── file_processor.py      # Directory processing logic
└── ui/                        # User interface components
    ├── __init__.py
    └── dialogs.py             # Dialog utilities

main.py                        # New main application launcher
```

## Features

- **Language-aware filtering**: Supports 15+ programming languages and file types
- **Intelligent file detection**: Automatically detects text files vs binary files
- **Gitignore support**: Respects .gitignore, .npmignore, and other ignore patterns
- **Progress tracking**: Real-time progress updates during processing
- **Multi-encoding support**: Handles various text encodings (UTF-8, Latin-1, etc.)
- **Professional UI**: Clean, responsive PyQt6 interface

## Usage

### Running the Application

**Recommended (new modular approach):**
```bash
python main.py
# or with uv:
uv run main.py
```

1. Select a project directory when prompted
2. Choose file types to include using the filter buttons
3. Navigate and select files/directories in the tree view
4. Click "Generate File" to create the concatenated output

## Architecture

The application follows a clean, modular architecture:

- **Separation of Concerns**: UI, business logic, and utilities are separated
- **Single Responsibility**: Each module has a focused purpose
- **Professional Structure**: Organized like a production application
- **Testable Design**: Components can be easily unit tested
- **Extensible**: Easy to add new features or file types

## Key Components

### Core Modules

- **`config.py`**: Contains all configuration dataclasses (`AppSettings`, `FilterSettings`, `GenerationOptions`, etc.)
- **`file_utils.py`**: Utility functions for file operations, ignore patterns, and file type detection
- **`language_definitions.py`**: Comprehensive language and file type definitions
- **`worker.py`**: Background worker thread for file processing with progress tracking
- **`main_window.py`**: Main PyQt6 application window with UI logic

### Core Business Logic (`core/`)

- **`file_reader.py`**: Handles reading files with multiple encoding fallbacks and error handling
- **`file_counter.py`**: Counts files for accurate progress tracking
- **`file_processor.py`**: Processes directories and files, respecting filters and ignore patterns

### UI Components (`ui/`)

- **`dialogs.py`**: Save file dialog and file writing operations

## Benefits of the Modular Structure

1. **Separation of Concerns**: Each module has a specific responsibility
2. **Maintainability**: Easier to locate and modify specific functionality
3. **Testability**: Individual modules can be tested in isolation
4. **Reusability**: Core logic can be reused in different contexts
5. **Readability**: Smaller, focused files are easier to understand

## Requirements

- Python 3.10+
- PyQt6
- pathspec
- atomicwrites

## Development

The modular structure makes it easy to:
- Add new language definitions in `language_definitions.py`
- Extend UI components in the `ui/` package
- Add new processing logic in the `core/` package
- Modify configuration in `config.py`
