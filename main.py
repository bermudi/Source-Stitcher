import argparse
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from tkinter import filedialog
import logging
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


class FileConcatenator(tk.Tk):
    """
    A tkinter-based graphical application to select and concatenate multiple files 
    into a single markdown file. Provides language-based filtering, search functionality, 
    and a preview of progress via a progress bar.
    """
    def __init__(self, working_dir: Path = None) -> None:
        super().__init__()
        
        self.working_dir = working_dir or Path.cwd()
        self.title("SOTA File Concatenator")
        self.geometry("700x500")

        # Define language extensions
        self.language_extensions: Dict[str, List[str]] = {
            "All Files": ["*"],
            "Python": [".py", ".pyw", ".pyx"],
            "JavaScript": [".js", ".jsx", ".ts", ".tsx"],
            "Java": [".java", ".class", ".jar"],
            "C/C++": [".c", ".cpp", ".h", ".hpp"],
            "Ruby": [".rb", ".rake"],
            "PHP": [".php"],
            "Go": [".go"],
            "Rust": [".rs"],
            "Swift": [".swift"],
            "HTML/CSS": [".html", ".htm", ".css"],
        }

        self.checkboxes: Dict[str, tk.BooleanVar] = {}
        self.create_widgets()
        self.populate_checkboxes()

    def create_widgets(self) -> None:
        """Create and place all the GUI components."""
        # Main frame
        self.main_frame = ttk.Frame(self)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Top filter/search frame
        self.top_frame = ttk.Frame(self.main_frame)
        self.top_frame.pack(fill=tk.X, padx=5, pady=5)

        # Language dropdown
        ttk.Label(self.top_frame, text="Language Filter:").pack(side=tk.LEFT, padx=5)
        self.language_var = tk.StringVar(value="All Files")
        self.language_dropdown = ttk.Combobox(
            self.top_frame,
            textvariable=self.language_var,
            values=list(self.language_extensions.keys()),
            state="readonly",
        )
        self.language_dropdown.pack(side=tk.LEFT, padx=(5, 25))
        self.language_dropdown.bind('<<ComboboxSelected>>', self.refresh_files)

        # Optional: Search box
        ttk.Label(self.top_frame, text="Search:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(self.top_frame, textvariable=self.search_var)
        self.search_entry.pack(side=tk.LEFT, padx=5)
        self.search_entry.bind("<KeyRelease>", self.refresh_files)

        # Scrollable frame for file/directory checkboxes
        self.canvas = tk.Canvas(self.main_frame)
        self.scrollbar = ttk.Scrollbar(self.main_frame, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        # Pack scrollbar and canvas
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Button frame
        self.button_frame = ttk.Frame(self)
        self.button_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Button(self.button_frame, text="Select All", command=self.select_all).pack(side=tk.LEFT, padx=5)
        ttk.Button(self.button_frame, text="Deselect All", command=self.deselect_all).pack(side=tk.LEFT, padx=5)

        # Progress bar
        self.progress_bar = ttk.Progressbar(self.button_frame, length=200, mode='determinate')
        self.progress_bar.pack(side=tk.LEFT, padx=25)

        ttk.Button(self.button_frame, text="Generate File", command=self.generate_file).pack(side=tk.RIGHT, padx=5)

    def populate_checkboxes(self) -> None:
        """Populate the scrollable frame with checkboxes for directories and files, filtered by language and search term."""
        # Clear existing checkboxes
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        self.checkboxes.clear()

        # Use working directory
        current_dir = self.working_dir

        # Get selected language and allowed extensions
        selected_language = self.language_var.get()
        allowed_extensions = self.language_extensions.get(selected_language, ["*"])

        # Apply a search filter
        search_text = self.search_var.get().lower().strip()

        # Gather all items in the current directory
        all_items = list(current_dir.iterdir())
        directories = []
        files = []

        for item in all_items:
            # Skip hidden files/folders or the script file itself
            if item.name.startswith('.') or item.name == Path(__file__).name:
                continue

            # If search text is present, apply it
            if search_text and search_text not in item.name.lower():
                continue

            if item.is_dir():
                directories.append(item)
            else:
                # Check if file is binary
                try:
                    with item.open('r', encoding='utf-8', errors='strict') as f:
                        f.read(1024)
                except UnicodeDecodeError:
                    logging.warning(f"Excluding binary file: {item}")
                    continue
                except Exception as e:
                    logging.error(f"Error checking file {item}: {e}")
                    continue

                if selected_language != "All Files":
                    if item.suffix.lower() not in allowed_extensions:
                        continue
                files.append(item)

        # Sort directories and files by name
        directories.sort(key=lambda p: p.name.lower())
        files.sort(key=lambda p: p.name.lower())

        # Add directories
        if directories:
            dir_label = ttk.Label(self.scrollable_frame, text="Directories:", font=('TkDefaultFont', 10, 'bold'))
            dir_label.pack(anchor="w", padx=5, pady=(5, 2))
            
            for directory in directories:
                var = tk.BooleanVar()
                cb = ttk.Checkbutton(self.scrollable_frame, text=directory.name, variable=var)
                cb.pack(anchor="w", padx=20, pady=2)  # Indented with larger left padding
                self.checkboxes[directory.name] = var

        # Add files
        if files:
            if directories:
                ttk.Separator(self.scrollable_frame, orient='horizontal').pack(fill='x', padx=5, pady=5)

            file_label = ttk.Label(self.scrollable_frame, text="Files:", font=('TkDefaultFont', 10, 'bold'))
            file_label.pack(anchor="w", padx=5, pady=(5, 2))

            for file_item in files:
                var = tk.BooleanVar()
                cb = ttk.Checkbutton(self.scrollable_frame, text=file_item.name, variable=var)
                cb.pack(anchor="w", padx=20, pady=2)
                self.checkboxes[file_item.name] = var

    def refresh_files(self, event=None) -> None:
        """Refresh the file/directory listings whenever the language filter or search changes."""
        self.populate_checkboxes()

    def select_all(self) -> None:
        """Select all checkboxes."""
        for var in self.checkboxes.values():
            var.set(True)

    def deselect_all(self) -> None:
        """Deselect all checkboxes."""
        for var in self.checkboxes.values():
            var.set(False)

    def get_file_content(self, filepath: Path) -> str:
        """
        Safely read the content of a file using UTF-8 encoding, skipping binary files.

        :param filepath: The path to the file.
        :return: Content of the file as a string or an empty string if binary.
        """
        try:
            # Attempt to read the file with strict error handling
            return filepath.read_text(encoding='utf-8', errors='strict')
        except UnicodeDecodeError:
            # File is likely binary
            logging.warning(f"Skipping binary file: {filepath}")
            return ""
        except Exception as e:
            logging.error(f"Error reading file {filepath}: {e}", exc_info=True)
            return f"Error reading file: {str(e)}"

    def process_directory(self, dir_path: Path, output_content: List[str], total_files: int, progress_step: float) -> None:
        """
        Recursively process a directory by appending the content of files 
        (matching the selected language filter) to output_content.

        :param dir_path: Path object representing the directory to process.
        :param output_content: List of strings to store file contents.
        :param total_files: Total number of files to process for the progress bar.
        :param progress_step: The amount (between 0 and 100) that each file adds to the progress bar.
        """
        selected_language = self.language_var.get()
        allowed_extensions = self.language_extensions[selected_language]

        for root, _, files in os.walk(dir_path):
            root_path = Path(root)
            for file_name in files:
                if file_name.startswith('.'):
                    continue
                if selected_language != "All Files":
                    if Path(file_name).suffix.lower() not in allowed_extensions:
                        continue

                full_path = root_path / file_name
                file_content = self.get_file_content(full_path)
                if not file_content:  # Skip binary or unreadable files
                    continue

                relative_path = full_path.relative_to(self.working_dir)
                ext = full_path.suffix[1:] if full_path.suffix else 'txt'
                output_content.append(f"\n{relative_path}")
                output_content.append(f"```{ext}")
                output_content.append(file_content)
                output_content.append("```\n")

                # Update the progress bar
                self.progress_bar["value"] += progress_step
                self.update_idletasks()

    def generate_file(self) -> None:
        """
        Generate a markdown file containing the concatenated contents of 
        selected files and directories. Displays a progress bar during the process.
        """
        output_content: List[str] = []
        current_dir = self.working_dir

        # Collect the files and directories that will actually be processed
        items_to_process = []
        for item_name, var in self.checkboxes.items():
            if var.get():
                items_to_process.append(item_name)

        if not items_to_process:
            messagebox.showwarning("No Selection", "Please select at least one file or directory.")
            return

        # Count how many files will be read for the progress bar
        # This is approximate—we simply count all files in selected directories + selected files.
        total_files = 0
        for item_name in items_to_process:
            full_path = current_dir / item_name
            if full_path.is_file():
                total_files += 1
            elif full_path.is_dir():
                for _ in full_path.rglob("*"):
                    total_files += 1

        # Guard against zero (in case all directories are empty)
        total_files = max(total_files, 1)
        progress_step = 100.0 / total_files
        self.progress_bar["value"] = 0.0

        # Process files and directories
        for item_name in items_to_process:
            full_path = current_dir / item_name
            if full_path.is_file():
                file_content = self.get_file_content(full_path)
                if not file_content:  # Skip binary or unreadable files
                    continue
                    
                ext = full_path.suffix[1:] if full_path.suffix else 'txt'
                output_content.append(f"\n{full_path.name}")
                output_content.append(f"```{ext}")
                output_content.append(file_content)
                output_content.append("```\n")

                self.progress_bar["value"] += progress_step
                self.update_idletasks()

            elif full_path.is_dir():
                self.process_directory(full_path, output_content, total_files, progress_step)

        # Generate output file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"concatenated_{timestamp}.md"

        try:
            with open(output_filename, 'w', encoding='utf-8') as f:
                f.write('\n'.join(output_content))
            messagebox.showinfo("Success", f"File generated: {output_filename}")
            logging.info(f"Successfully generated file: {output_filename}")
        except Exception as e:
            logging.error(f"Error writing output file {output_filename}: {e}", exc_info=True)
            messagebox.showerror("Error", f"Could not write output file:\n{e}")

        # Reset progress bar
        self.progress_bar["value"] = 0.0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="File Concatenator Application")
    parser.add_argument(
        "--dir", 
        type=Path, 
        default=Path.cwd(),
        help="The working directory to use."
    )
    args = parser.parse_args()
    
    # Validate if directory exists
    if not args.dir.exists() or not args.dir.is_dir():
        print(f"Error: Directory '{args.dir}' does not exist or is not a directory")
        exit(1)
        
    app = FileConcatenator(working_dir=args.dir)
    app.mainloop()
