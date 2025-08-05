# Source Stitcher

A PyQt6-based application for concatenating multiple source code files with intelligent filtering and language detection.


![Screenshot 1](https://i.postimg.cc/8CyDPymp/Screenshot-20250730-185558.png)

![Screenshot 2](https://i.postimg.cc/t40v75r9/Screenshot-20250728-152107.png)


## Project Structure

 
```
src/
├── __init__.py                # Package initialization
├── config.py                  # Configuration dataclasses
├── file_utils.py              # File utility functions
├── language_definitions.py    # Language definitions dispatcher (TOML-backed)
├── logging_config.py          # Logging configuration
├── version.py                 # Version management utilities
├── worker.py                  # Background worker thread
├── core/                      # Core business logic
│   ├── __init__.py
│   ├── file_reader.py         # File reading with encoding detection
│   ├── file_walker.py         # Unified discovery & filtering (gitignore, sizes, duplicates)
│   ├── output_builder.py      # HeaderBuilder + ContentStreamer (markdown/plain/json)
│   ├── tree_generator.py      # ASCII tree for header
│   └── language_loader.py     # Loads TOML-backed language definitions (creates default if missing)
├── cli/                       # Command line interface
│   ├── __init__.py
│   ├── config.py              # CLI configuration
│   ├── info.py                # CLI info commands
│   ├── parser.py              # Argument parsing
│   ├── progress.py            # CLI progress display
│   └── runner.py              # CLI execution logic
└── ui/                        # User interface components
    ├── __init__.py
    ├── dialogs.py             # Dialog utilities
    └── main_window.py         # Main application window

main.py                        # Main application launcher
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

#### Option 1: Quick Start with [`uv`](https://github.com/astral-sh/uv) (Recommended)

If you have [uv](https://github.com/astral-sh/uv) installed, you don’t need to manually create a virtual environment or install dependencies:

```bash
# Run directly (no manual setup needed):
uv run main.py

# Or via entry point (if installed as a package):
uv run source-stitcher
```

#### Option 2: Manual Setup with Virtual Environment

If you prefer or need to use the classic Python tooling:

```bash
# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate   # On Windows use: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

> **Tip:** Using `uv run ...` is the easiest way to avoid virtual environment and dependency headaches!

1. Select a project directory when prompted
2. Choose file types to include using the filter buttons
3. Navigate and select files/directories in the tree view
4. Click "Generate File" to create the concatenated output

### CLI Usage

Run in CLI mode:

```bash
source-stitcher --cli /path/to/project --output result.md
```

Common options:
- Filter by types: `--include-types python,javascript` or `--exclude-types documentation,config`
- Filter by extensions: `--include-extensions .py,.js` and `--exclude-extensions .pyc,.log`
- Ignore controls: `--no-gitignore` or `--ignore-file path/to/ignorefile`
- Output format: `--format markdown|plain|json`, `--encoding utf-8`, `--line-ending unix|windows|mac`
- Progress/logging: `--progress`, `--verbose` or `--quiet`
- Overwrite existing output: `--overwrite`

Info commands:

```bash
source-stitcher --list-types
source-stitcher --version
```

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
- **`language_definitions.py`**: Language definitions dispatcher delegating to TOML via `core/language_loader.py`
- **`worker.py`**: Background worker thread for file processing with progress tracking
- **`main_window.py`**: Main PyQt6 application window with UI logic

### Core Business Logic (`core/`)

- **`file_reader.py`**: Handles reading files with multiple encoding fallbacks and error handling
- **`file_walker.py`**: Unified file discovery and filtering honoring ignore patterns, size limits, and duplicate detection
- **`output_builder.py`**: Builds headers and streams content efficiently (markdown/plain/json)
- **`tree_generator.py`**: Generates an ASCII tree for the header
- **`language_loader.py`**: Loads TOML-backed language definitions (creates default if missing)

### UI Components (`ui/`)

- **`dialogs.py`**: Save file dialog and file writing operations

### CLI Components (`cli/`)

- **`parser.py`**: Argument parsing, help text, examples; handles `--version` and `--list-types`
- **`config.py`**: `CLIConfig` and conversion to internal `FilterSettings`/`GenerationOptions`
- **`progress.py`**: CLI progress reporter
- **`runner.py`**: Runs the worker and finalizes the output file
- **`info.py`**: Displays supported file types and version info

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
- tomli (for Python < 3.11)

## Development

The modular structure makes it easy to:
- Add or modify language definitions in `language_definitions.toml` (loaded by `core/language_loader.py`)
- Extend UI components in the `ui/` package
- Add new processing logic in the `core/` package
- Modify configuration in `config.py`

## How It Works

- Discovery: `core/file_walker.py` traverses the directory once, applying ignore patterns (`.gitignore`, global gitignore, custom ignores), extension/type filters, size limits, and duplicate inode checks.
- Header: `core/output_builder.py` (`HeaderBuilder`) composes a markdown header with project info, selected types, directory stats, and an ASCII file tree from `core/tree_generator.py`.
- Streaming: `core/output_builder.py` (`ContentStreamer`) writes each file in sequence to a temp file, wrapping contents in fenced code blocks by inferred language. Encoding fallbacks are handled by `core/file_reader.py`.
- Finalization: The temp file is atomically written to the chosen destination (GUI via `ui/dialogs.py`; CLI via `cli/runner.py`).

## Example Output (Markdown)

Header and file tree:

```text
# Source Stitcher Export

- Base directory: /path/to/project
- Generated: 2025-08-04 17:50:00
- Selected types: Python, JavaScript

## File Tree

project
├── src
│   ├── app.py
│   └── utils.js
└── README.md

---
```

Example file blocks:

```python
# app.py
def main():
    print("Hello")
```

```javascript
// utils.js
export const sum = (a, b) => a + b;
```

## Troubleshooting

- Nothing selected? Ensure filters include the languages you expect and that `.gitignore` isn’t excluding your files. Use `--no-gitignore` or `--ignore-file` to adjust.
- Encoding issues? Files are read with multiple fallbacks. If you still see garbled text, try exporting with `--encoding utf-16`.
- Large repos? Increase `--max-file-size` (MB) or limit with `--include-types`/`--include-extensions`. Progress output can be enabled with `--progress`.
- Overwrite prompts in CLI? Add `--overwrite`.

## Extending Language Definitions

Language and file type categories are defined in `language_definitions.toml` and loaded by `core/language_loader.py`.

- Each section represents a category name. Use underscores for spaces (e.g., `Web_Frontend`).
- Supported keys per section:
  - `extensions`: list of extensions including the dot
  - `filenames`: list of specific filenames matched exactly (case-insensitive)
  - `description`: optional human-readable text

Example:

```toml
[Python]
extensions = [".py"]
filenames  = ["pyproject.toml", "requirements.txt"]
description = "Python source files and configuration"

[Web_Frontend]
extensions = [".html", ".css", ".js", ".ts"]
filenames  = ["package.json", "vite.config.ts"]
description = "Frontend web assets and config"

[Other_Text_Files]
extensions = []
filenames  = ["*other*"]
description = "Other text files"
```

Tip: If the TOML file is missing or invalid, the app creates a default one you can edit.
