"""Output building components for streaming file content efficiently."""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List, TextIO, Optional, Callable, Tuple

from .tree_generator import ProjectTreeGenerator
from .file_reader import FileReader

logger = logging.getLogger(__name__)


class HeaderBuilder:
    """Builds the complete markdown header before any file content is written."""

    def __init__(self, base_dir: Path, file_list: List[Path], selected_langs: List[str]):
        """Initialize the header builder.
        
        Args:
            base_dir: Base directory for the project
            file_list: List of files to be processed
            selected_langs: List of selected language names
        """
        self.base_dir = base_dir
        self.file_list = file_list
        self.selected_langs = selected_langs

    def build(self) -> str:
        """Build the complete header string.
        
        Returns:
            Complete header as a string
        """
        # Generate tree structure
        tree_generator = ProjectTreeGenerator(self.base_dir)
        tree = tree_generator.generate_tree(self.file_list)
        
        # Compute human-readable total size of the working directory
        total_bytes = self._compute_directory_size(self.base_dir)
        human_size = self._format_size(total_bytes)
        
        # Build header components
        header_lines = [
            f"# Concatenated Files from: {self.base_dir}",
            f"# Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"# Total directory size: {human_size}",
        ]
        
        # Add selected file types info
        if not self.selected_langs:
            header_lines.append("# Selected file types: All types")
        else:
            header_lines.append(f"# Selected file types: {', '.join(self.selected_langs)}")
        
        # Add tree section
        header_lines.extend([
            "",
            "# Selected Files",
            "```",
            tree,
            "```",
            "",
            "=" * 60,
            "START OF CONCATENATED CONTENT",
            "=" * 60,
            "",
        ])
        
        return "\n".join(header_lines)
    
    def _compute_directory_size(self, root: Path) -> int:
        """Compute total size of directory in bytes.
        
        Args:
            root: Root directory to compute size for
            
        Returns:
            Total size in bytes
        """
        total = 0
        try:
            for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
                # Skip hidden directories quickly
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for name in filenames:
                    if name.startswith("."):
                        continue
                    fp = Path(dirpath) / name
                    try:
                        if fp.is_file():
                            total += fp.stat().st_size
                    except (OSError, PermissionError):
                        continue
        except Exception as e:
            logger.warning(f"Error computing directory size for {root}: {e}")
        return total
    
    def _format_size(self, num_bytes: int) -> str:
        """Format bytes as human-readable string.
        
        Args:
            num_bytes: Number of bytes
            
        Returns:
            Human-readable size string
        """
        for unit in ["bytes", "KB", "MB", "GB", "TB"]:
            if num_bytes < 1024.0 or unit == "TB":
                return (
                    f"{num_bytes:.2f} {unit}"
                    if unit != "bytes"
                    else f"{int(num_bytes)} {unit}"
                )
            num_bytes /= 1024.0
        return f"{num_bytes:.2f} TB"


class ContentStreamer:
    """Streams file content directly to output handle without intermediate storage."""

    def __init__(self, file_reader: FileReader, output_fh: TextIO):
        """Initialize the content streamer.
        
        Args:
            file_reader: FileReader instance for reading file content
            output_fh: Output file handle to write to
        """
        self.reader = file_reader
        self.out = output_fh

    def stream_files(
        self,
        files: List[Path],
        base_dir: Path,
        progress_cb: Optional[Callable[[int], None]] = None,
    ) -> Tuple[int, List[Path]]:
        """Stream file contents directly to output.
        
        Args:
            files: List of files to stream
            base_dir: Base directory for relative path calculation
            progress_cb: Optional progress callback function
            
        Returns:
            Tuple of (number of files successfully processed, list of processed files)
        """
        total = len(files)
        processed_count = 0
        processed_files = []
        
        for idx, path in enumerate(files, 1):
            try:
                content = self.reader.get_file_content(path)
                if content is None:
                    logger.debug(f"Skipping file with no content: {path}")
                    continue
                
                # Calculate relative path and language
                try:
                    rel_path = path.relative_to(base_dir)
                except ValueError:
                    logger.warning(f"Could not make path relative: {path}")
                    rel_path = path
                
                lang = path.suffix[1:] if path.suffix else "txt"
                
                # Write file section
                self.out.write(f"\n--- File: {rel_path} ---\n")
                self.out.write(f"```{lang}\n")
                self.out.write(content)
                self.out.write("\n```\n")
                
                processed_count += 1
                processed_files.append(path)
                
                # Update progress
                if progress_cb and total > 0:
                    progress_cb(int(idx / total * 100))
                    
            except Exception as e:
                logger.error(f"Error streaming file {path}: {e}")
                continue
        
        # Write footer
        self.out.write("\n" + "=" * 60 + "\n")
        self.out.write("END OF CONCATENATED CONTENT\n")
        self.out.write("=" * 60 + "\n")
        
        logger.info(f"Content streaming completed: {processed_count}/{total} files processed")
        return processed_count, processed_files