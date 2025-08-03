# Logging Enhancement Plan for Source Stitcher

## 🎯 Objective
Add comprehensive debug and info-level logging across all core modules to improve troubleshooting capabilities and provide better visibility into the application's operation.

## 📊 Current State Analysis

### ✅ What's Working Well
- **Solid logging infrastructure** in `src/logging_config.py` with proper level handling
- **CLI support** for `--verbose`, `--quiet`, and `--log-level` options  
- **Basic logging** present in core files (mostly warnings and errors)
- **Proper log level configuration** that respects user preferences

### ❌ What Needs Improvement
- **Missing debug-level logging** for detailed troubleshooting
- **Insufficient info-level logging** for process tracking
- **Inconsistent logger usage** (some files use root logger vs named loggers)
- **Limited visibility** into internal processing steps

## 📋 Files Requiring Logging Updates

### 🔥 **High Priority - Core Processing Files**

#### 1. `src/core/file_reader.py`
**Current Issues:**
- Only logs warnings and basic info
- Missing debug info for encoding attempts
- No performance metrics

**Enhancements Needed:**
```python
# Add at top
logger = logging.getLogger(__name__)

# Debug logging examples:
logger.debug(f"Attempting to read file: {filepath.name} ({filepath.stat().st_size} bytes)")
logger.debug(f"Trying encoding: {encoding}")
logger.debug(f"Successfully decoded with {encoding} in {time:.3f}s")
logger.debug(f"File content preview: {content[:100]}...")

# Info logging examples:
logger.info(f"Processing file: {filepath.name}")
logger.info(f"Fallback to chunked reading for large file: {filepath.name}")
```

#### 2. `src/core/file_processor.py`
**Current Issues:**
- Limited logging of processing decisions
- No visibility into filter applications
- Missing progress indicators

**Enhancements Needed:**
```python
# Add at top
logger = logging.getLogger(__name__)

# Debug logging examples:
logger.debug(f"Starting directory traversal: {dir_path}")
logger.debug(f"Applying filters to file: {full_path}")
logger.debug(f"File {file_name} passed all filters")
logger.debug(f"Writing file content: {relative_path_output}")

# Info logging examples:
logger.info(f"Processing directory: {dir_path} ({len(files)} files)")
logger.info(f"Processed {files_processed_counter[0]} files so far")
```

#### 3. `src/core/file_counter.py`
**Current Issues:**
- No logging of counting logic
- Missing performance metrics
- No visibility into filter decisions

**Enhancements Needed:**
```python
# Add at top
logger = logging.getLogger(__name__)

# Debug logging examples:
logger.debug(f"Counting files in directory: {dir_path}")
logger.debug(f"File {file_name} matches criteria, count: {count}")
logger.debug(f"Directory {d} excluded by ignore patterns")

# Info logging examples:
logger.info(f"File counting started for: {dir_path}")
logger.info(f"Found {count} matching files in directory")
```

#### 4. `src/worker.py`
**Current Issues:**
- Limited worker lifecycle logging
- Missing progress tracking details
- No cancellation state logging

**Enhancements Needed:**
```python
# Add at top
logger = logging.getLogger(__name__)

# Debug logging examples:
logger.debug(f"Worker initialized with config: {self.config}")
logger.debug(f"Starting pre-scan phase")
logger.debug(f"Processing item: {path.name}")
logger.debug(f"Worker cancellation requested: {self._is_cancelled}")

# Info logging examples:
logger.info(f"Worker starting processing of {len(paths)} items")
logger.info(f"Pre-scan completed: {total_files} files found")
logger.info(f"Processing phase completed: {files_processed_count} files processed")
```

### 🔶 **Medium Priority - Utility and Configuration Files**

#### 5. `src/file_utils.py`
**Current Issues:**
- No debug logging for binary detection
- Missing ignore pattern matching details
- No file type detection logging

**Enhancements Needed:**
```python
logger = logging.getLogger(__name__)

# Debug logging for binary detection, ignore patterns, file matching
logger.debug(f"Checking if file is binary: {filepath}")
logger.debug(f"Loading ignore patterns from: {directory}")
logger.debug(f"File {filepath} matches type criteria: {matches}")
```

#### 6. `src/config.py`
**Current Issues:**
- No logging of configuration loading
- Missing validation step logging

**Enhancements Needed:**
```python
logger = logging.getLogger(__name__)

# Debug logging for config loading and validation
logger.debug(f"Loading configuration with settings: {settings}")
logger.debug(f"Configuration validation completed")
```

#### 7. `src/cli/runner.py`
**Current Issues:**
- Limited CLI workflow logging
- Missing temporary file handling details

**Enhancements Needed:**
```python
logger = logging.getLogger(__name__)

# Debug logging for CLI operations
logger.debug(f"CLI processing started with config: {cli_config}")
logger.debug(f"Temporary file created: {temp_file}")
logger.debug(f"Moving temporary file to final location: {cli_config.output_file}")
```

### 🔷 **Lower Priority - UI and Support Files**

#### 8. `src/ui/main_window.py`
**Enhancements:** Debug logging for UI state changes, file tree operations, user interactions

#### 9. `src/ui/dialogs.py`
**Enhancements:** Debug logging for dialog operations and file I/O

#### 10. `src/cli/progress.py`
**Enhancements:** Debug logging for progress calculations

#### 11. `main.py`
**Enhancements:** Debug logging for application startup and mode selection

## 🔧 Logging Enhancement Strategy

### **Debug Level Logging (`logging.debug`)**
- **File processing steps**: Individual file operations and their results
- **Filter decisions**: Why files were included/excluded
- **Performance metrics**: Timing information for operations
- **Configuration details**: Settings being applied
- **Internal state changes**: Worker states, UI states, etc.

### **Info Level Logging (`logging.info`)**
- **Process milestones**: Major workflow steps completed
- **Summary statistics**: Counts, totals, completion status
- **User actions**: Directory selections, button clicks
- **Successful operations**: Completed processes with results
- **Configuration changes**: Applied filters and settings

### **Best Practices to Implement**

1. **Use Named Loggers**
   ```python
   logger = logging.getLogger(__name__)
   ```

2. **Conditional Expensive Operations**
   ```python
   if logger.isEnabledFor(logging.DEBUG):
       logger.debug(f"Expensive operation result: {expensive_calculation()}")
   ```

3. **Consistent Message Format**
   ```python
   logger.debug(f"Operation: {operation_name} - File: {filename} - Result: {result}")
   ```

4. **Performance-Aware Logging**
   - Avoid logging in tight loops unless at debug level
   - Use lazy evaluation for expensive string formatting

5. **Structured Information**
   - Include relevant metadata (file sizes, counts, timing)
   - Use consistent terminology across modules

## 📈 Implementation Phases

### **Phase 1: Core Processing Enhancement** (High Priority)
- [ ] Update `src/core/file_reader.py`
- [ ] Update `src/core/file_processor.py`
- [ ] Update `src/core/file_counter.py`
- [ ] Update `src/worker.py`

### **Phase 2: Utility and Configuration Enhancement** (Medium Priority)
- [ ] Update `src/file_utils.py`
- [ ] Update `src/config.py`
- [ ] Update `src/cli/runner.py`

### **Phase 3: UI and Support Enhancement** (Lower Priority)
- [ ] Update `src/ui/main_window.py`
- [ ] Update `src/ui/dialogs.py`
- [ ] Update `src/cli/progress.py`
- [ ] Update `main.py`

## 🎯 Expected Benefits

1. **Better Troubleshooting**
   - Debug logs will help identify where processing fails or slows down
   - Detailed error context for faster issue resolution

2. **Performance Monitoring**
   - Info logs will show processing progress and statistics
   - Timing information for performance optimization

3. **User Experience**
   - Better visibility into what the application is doing
   - More informative progress reporting

4. **Development Support**
   - Easier debugging during development and testing
   - Better understanding of application flow

5. **Production Monitoring**
   - Better insights into application behavior in production
   - Proactive issue identification

## 📝 Code Examples

### Before and After Comparison

#### File Reader Enhancement
```python
# BEFORE
def get_file_content(self, filepath: Path) -> Optional[str]:
    if is_binary_file(filepath):
        logging.warning(f"Skipping binary file detected during read: {filepath.name}")
        return None
    
    for encoding in self.encodings:
        try:
            content = filepath.read_text(encoding=encoding, errors="strict")
            return content
        except UnicodeDecodeError:
            continue

# AFTER
def get_file_content(self, filepath: Path) -> Optional[str]:
    logger = logging.getLogger(__name__)
    
    logger.debug(f"Reading file: {filepath.name} ({filepath.stat().st_size} bytes)")
    
    if is_binary_file(filepath):
        logger.info(f"Skipping binary file: {filepath.name}")
        return None
    
    for encoding in self.encodings:
        logger.debug(f"Trying encoding: {encoding} for file: {filepath.name}")
        try:
            start_time = time.time()
            content = filepath.read_text(encoding=encoding, errors="strict")
            read_time = time.time() - start_time
            
            logger.debug(f"Successfully read {filepath.name} with {encoding} in {read_time:.3f}s")
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Content preview: {content[:100]}...")
            
            return content
        except UnicodeDecodeError as e:
            logger.debug(f"Encoding {encoding} failed for {filepath.name}: {e}")
            continue
```

## 🔍 Testing Strategy

1. **Test with Different Log Levels**
   - Run with `--log-level DEBUG` to verify all debug messages
   - Run with `--log-level INFO` to verify info messages
   - Run with `--quiet` to ensure only errors show

2. **Performance Testing**
   - Verify debug logging doesn't significantly impact performance
   - Test with large directories to ensure logging scales well

3. **Integration Testing**
   - Test both CLI and GUI modes with enhanced logging
   - Verify log messages are helpful and not overwhelming

## 📋 Implementation Checklist

### Pre-Implementation
- [ ] Review this plan and get approval
- [ ] Set up test environment with sample projects
- [ ] Create backup of current codebase

### Implementation Tracking
- [ ] **Phase 1 Complete**: Core processing files updated
- [ ] **Phase 2 Complete**: Utility and configuration files updated  
- [ ] **Phase 3 Complete**: UI and support files updated
- [ ] **Testing Complete**: All log levels tested
- [ ] **Documentation Updated**: README and comments updated
- [ ] **Performance Verified**: No significant performance impact

### Post-Implementation
- [ ] Update user documentation with logging information
- [ ] Create troubleshooting guide using new log messages
- [ ] Monitor for any issues with new logging in production