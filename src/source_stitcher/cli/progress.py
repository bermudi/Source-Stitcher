"""CLI progress reporting."""

import logging
import sys
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class CLIProgressReporter:
    """Progress reporter for CLI mode that connects to worker signals."""

    def __init__(self, show_progress: bool = False, quiet: bool = False):
        self.show_progress = show_progress
        self.quiet = quiet
        self.total_files = 0
        self.processed_files = 0
        self.start_time: Optional[float] = None
        logger.debug(
            f"CLIProgressReporter initialized with show_progress={show_progress}, quiet={quiet}"
        )

    def on_status_updated(self, status: str):
        """Handle status updates from worker."""
        if self.show_progress and not self.quiet:
            print(f"Status: {status}", file=sys.stderr)
        logger.info(f"Worker status: {status}")

    def on_progress_updated(self, progress: int):
        """Handle progress updates from worker."""
        if self.show_progress and not self.quiet:
            print(f"Progress: {progress}%", file=sys.stderr)
        logger.debug(f"Worker progress updated to {progress}%")

    def on_pre_count_finished(self, total_files: int):
        """Handle pre-count completion."""
        self.total_files = total_files
        if self.show_progress and not self.quiet:
            print(f"Found {total_files} files to process", file=sys.stderr)
        logger.info(f"Pre-count completed: {total_files} files found")

        self.start_time = time.time()
        logger.debug(f"Processing start time recorded: {self.start_time}")

    def get_summary_stats(self, output_file: Path) -> dict:
        """Generate summary statistics for final output."""
        logger.debug("Calculating summary stats...")
        stats = {
            "total_files_found": self.total_files,
            "processing_time": None,
            "output_size": 0,
        }

        if self.start_time:
            stats["processing_time"] = time.time() - self.start_time

        if output_file.exists():
            stats["output_size"] = output_file.stat().st_size

        logger.debug(f"Summary stats calculated: {stats}")
        return stats

    def print_summary(self, output_file: Path):
        """Print final summary statistics."""
        if self.quiet:
            return

        stats = self.get_summary_stats(output_file)

        print(
            f"Successfully processed {stats['total_files_found']} files",
            file=sys.stderr,
        )
        print(f"Output written to: {output_file}", file=sys.stderr)
        print(f"Output file size: {stats['output_size']:,} bytes", file=sys.stderr)

        if stats["processing_time"]:
            print(
                f"Processing time: {stats['processing_time']:.2f} seconds",
                file=sys.stderr,
            )

        logger.info(f"Processing completed successfully: {stats}")
