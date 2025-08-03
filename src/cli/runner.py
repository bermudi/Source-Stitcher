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

logger = logging.getLogger(__name__)


def run_cli_mode(cli_config: CLIConfig) -> int:
    """
    Run the application in CLI mode using the existing worker.
    
    Args:
        cli_config: CLI configuration object
        
    Returns:
        Exit code (0 for success, non-zero for errors)
    """
    logger.info(f"Starting CLI processing: {cli_config.directory}")
    logger.debug(f"CLI processing started with config: {cli_config}")
    try:
        app = QtCore.QCoreApplication(sys.argv)
        
        filter_settings = cli_config.to_filter_settings()
        generation_options = cli_config.to_generation_options()
        
        worker_config = WorkerConfig(
            filter_settings=filter_settings,
            generation_options=generation_options
        )
        logger.debug(f"WorkerConfig created: {worker_config}")
        
        worker = GeneratorWorker(worker_config)
        
        progress_reporter = CLIProgressReporter(
            show_progress=cli_config.progress,
            quiet=cli_config.quiet
        )
        
        completion_state = {"finished": False, "temp_file": None, "error": None}
        
        def on_finished(temp_file: str, error_message: str):
            """Handle worker completion."""
            logger.debug(f"Worker finished - temp_file: {temp_file}, error: {error_message}")
            if temp_file:
                logger.debug(f"Temporary file created: {temp_file}")
            completion_state["finished"] = True
            completion_state["temp_file"] = temp_file
            completion_state["error"] = error_message
            app.quit()
        
        worker.status_updated.connect(progress_reporter.on_status_updated)
        worker.progress_updated.connect(progress_reporter.on_progress_updated)
        worker.pre_count_finished.connect(progress_reporter.on_pre_count_finished)
        worker.finished.connect(on_finished)
        
        logger.debug(f"Filter settings: {filter_settings}")
        logger.debug(f"Generation options: {generation_options}")
        
        if not cli_config.recursive:
            logger.warning("--no-recursive option is not fully supported in current implementation. Processing will still be recursive.")
        
        if cli_config.include_hidden:
            logger.warning("--include-hidden option is not fully supported in current implementation. Hidden files will still be excluded.")
        
        QtCore.QTimer.singleShot(0, worker.run)
        
        app.exec()
        
        if completion_state["error"]:
            logger.error(f"Processing failed: {completion_state['error']}")
            return 4
        
        if not completion_state["temp_file"]:
            logger.error("No output file generated")
            return 4
        
        try:
            if cli_config.output_file.exists() and not cli_config.overwrite:
                logger.error(f"Output file already exists: {cli_config.output_file}")
                logger.error("Use --overwrite flag to overwrite existing files")
                temp_path = Path(completion_state["temp_file"])
                if temp_path.exists():
                    temp_path.unlink()
                return 5
            
            cli_config.output_file.parent.mkdir(parents=True, exist_ok=True)
            
            logger.debug(f"Moving temporary file {completion_state['temp_file']} to final location: {cli_config.output_file}")
            shutil.move(completion_state["temp_file"], cli_config.output_file)
            
            logger.info(f"CLI processing complete. Output written to: {cli_config.output_file}")
            
            progress_reporter.print_summary(cli_config.output_file)
            
            return 0
            
        except OSError as e:
            logger.error(f"Failed to write output file: {e}")
            temp_path = Path(completion_state["temp_file"])
            if temp_path.exists():
                temp_path.unlink()
            return 5
        
    except KeyboardInterrupt:
        logger.info("Operation cancelled by user")
        return 130
    except Exception as e:
        logger.error(f"Unexpected error in CLI mode: {e}", exc_info=True)
        return 1