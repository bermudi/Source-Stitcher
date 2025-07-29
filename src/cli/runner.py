"""CLI mode execution."""

import logging
import shutil
import sys
from pathlib import Path

from PyQt6 import QtCore

from ..config import WorkerConfig
from ..worker import GeneratorWorker
from .config import CLIConfig
from .progress import CLIProgressReporter


def run_cli_mode(cli_config: CLIConfig) -> int:
    """
    Run the application in CLI mode using the existing worker.
    
    Args:
        cli_config: CLI configuration object
        
    Returns:
        Exit code (0 for success, non-zero for errors)
    """
    try:
        # Set up minimal QCoreApplication for CLI mode to support Qt-based worker
        app = QtCore.QCoreApplication(sys.argv)
        
        # Convert CLI config to worker configuration
        filter_settings = cli_config.to_filter_settings()
        generation_options = cli_config.to_generation_options()
        
        worker_config = WorkerConfig(
            filter_settings=filter_settings,
            generation_options=generation_options
        )
        
        # Create and configure the worker
        worker = GeneratorWorker(worker_config)
        
        # Create progress reporter
        progress_reporter = CLIProgressReporter(
            show_progress=cli_config.progress,
            quiet=cli_config.quiet
        )
        
        # Track completion state
        completion_state = {"finished": False, "temp_file": None, "error": None}
        
        def on_finished(temp_file: str, error_message: str):
            """Handle worker completion."""
            logging.debug(f"Worker finished - temp_file: {temp_file}, error: {error_message}")
            completion_state["finished"] = True
            completion_state["temp_file"] = temp_file
            completion_state["error"] = error_message
            app.quit()
        
        # Connect worker signals to progress reporter and completion handler
        worker.status_updated.connect(progress_reporter.on_status_updated)
        worker.progress_updated.connect(progress_reporter.on_progress_updated)
        worker.pre_count_finished.connect(progress_reporter.on_pre_count_finished)
        worker.finished.connect(on_finished)
        
        # Log configuration and limitations
        logging.info(f"Starting CLI processing of directory: {cli_config.directory}")
        logging.debug(f"Filter settings: {filter_settings}")
        logging.debug(f"Generation options: {generation_options}")
        
        # Warn about unsupported options due to current architecture limitations
        if not cli_config.recursive:
            logging.warning("--no-recursive option is not fully supported in current implementation. Processing will still be recursive.")
        
        if cli_config.include_hidden:
            logging.warning("--include-hidden option is not fully supported in current implementation. Hidden files will still be excluded.")
        
        # Use QTimer to start worker in the next event loop iteration
        QtCore.QTimer.singleShot(0, worker.run)
        
        # Run the event loop until worker completes
        app.exec()
        
        # Handle completion
        if completion_state["error"]:
            logging.error(f"Processing failed: {completion_state['error']}")
            return 4  # Processing error exit code
        
        if not completion_state["temp_file"]:
            logging.error("No output file generated")
            return 4  # Processing error exit code
        
        # Move temporary file to specified output location
        try:
            # Check if output file already exists and handle overwrite
            if cli_config.output_file.exists() and not cli_config.overwrite:
                logging.error(f"Output file already exists: {cli_config.output_file}")
                logging.error("Use --overwrite flag to overwrite existing files")
                # Clean up temp file
                temp_path = Path(completion_state["temp_file"])
                if temp_path.exists():
                    temp_path.unlink()
                return 5  # Output file error exit code
            
            # Ensure output directory exists
            cli_config.output_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Move temp file to final location
            shutil.move(completion_state["temp_file"], cli_config.output_file)
            
            logging.info(f"Output written to: {cli_config.output_file}")
            
            # Print summary statistics using progress reporter
            progress_reporter.print_summary(cli_config.output_file)
            
            return 0  # Success
            
        except OSError as e:
            logging.error(f"Failed to write output file: {e}")
            # Clean up temp file
            temp_path = Path(completion_state["temp_file"])
            if temp_path.exists():
                temp_path.unlink()
            return 5  # Output file error exit code
        
    except KeyboardInterrupt:
        logging.info("Operation cancelled by user")
        return 130  # Standard exit code for SIGINT
    except Exception as e:
        logging.error(f"Unexpected error in CLI mode: {e}", exc_info=True)
        return 1  # General error exit code