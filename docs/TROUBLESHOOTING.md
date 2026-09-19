# Troubleshooting Guide

## Installation Issues

### Inkscape Not Found

**Error:** `Inkscape executable not found`

**Solutions:**
1. Install Inkscape from the official website
2. Add Inkscape to your system PATH
3. Specify the full path in `config.yaml`:
   ```yaml
   inkscape_executable: "/path/to/inkscape.exe"
   ```

### Python Version Issues

**Error:** `Python version not supported`

**Solutions:**
- Use Python 3.10 or higher
- Check version with `python --version`
- Create virtual environment with correct Python version

### Dependency Installation Failed

**Error:** `pip install` fails

**Solutions:**
- Upgrade pip: `python -m pip install --upgrade pip`
- Use virtual environment
- Check network connectivity
- Install build dependencies (Linux/macOS)

## Runtime Issues

### Native crash in `active_window_end_helper` / `sp_repr_save_stream`

Inkscape's internal `active-window-start` and `active-window-end` actions manage
the live GUI command bridge. Calling them directly or out of sequence can crash
the native document saver; [upstream issue #4765](https://gitlab.com/inkscape/inkscape/-/issues/4765)
contains this stack trace. This is a matching failure path, not proof of the
trigger for every crash with these frames.

The MCP server rejects these internal actions before launching Inkscape, including
inside semicolon-separated commands and shell sessions. Use ordinary editing
actions in `hands_in_command`; Inkscape manages the bridge itself. Live GUI
commands are serialized within each CLI wrapper. Independent MCP server processes
or other clients can still compete for the same GUI, so use file-based operations
for concurrent automation.

Batch commands use separate application IDs. Managed CLI exports write a temporary
file beside the destination and replace the destination only after successful
execution and output checks (SVG XML, PNG integrity, PDF header/trailer).
Failures, timeouts and cancellation preserve the existing destination. Unknown
actions and missing object IDs are errors even when Inkscape exits with status 0;
GTK/font warnings remain in logs rather than contaminating numeric query results.

Restart the MCP connection after updating the server. These protections cannot
guarantee that every native Inkscape bug is avoided. When reporting a remaining
crash, include the action sequence and a minimal SVG that reproduces it.

To run the runtime regressions with a real Inkscape installation:

```bash
uv run pytest tests/integration/test_inkscape_runtime.py -o addopts='' -q
```

The tests skip if Inkscape is unavailable. Run them in a normal desktop environment
when testing raster imports: restrictive sandboxes may block the Glycin image
loader's D-Bus communication on Linux.

### Operation Timeout

**Error:** `Operation timed out`

**Solutions:**
- Increase timeout in config:
  ```yaml
  process_timeout: 60
  ```
- Check system resources (CPU/memory)
- Simplify the operation or reduce file size

### File Not Found

**Error:** `Input file not found`

**Solutions:**
- Use absolute paths
- Check file permissions
- Ensure file exists before operation
- Verify working directory

### Invalid SVG Format

**Error:** `Invalid or corrupted SVG file`

**Solutions:**
- Validate SVG with `inkscape_file(operation="validate")`
- Check SVG namespace declarations
- Repair with text editor if necessary
- Use well-formed SVG sources

## AI Generation Issues

### Generation Failed

**Error:** `AI model generation failed`

**Solutions:**
- Check network connectivity for AI services
- Verify API keys if required
- Try different model or quality settings
- Reduce description complexity

### Quality Issues

**Problem:** Generated SVG quality is poor

**Solutions:**
- Use higher quality settings
- Provide more detailed descriptions
- Use appropriate style presets
- Apply post-processing operations

### Style Not Applied

**Problem:** Style preset not working as expected

**Solutions:**
- Verify preset name spelling
- Try different style presets
- Provide style hints in description
- Check generation logs

## Extension Issues

### Extension Not Found

**Error:** `Extension not available`

**Solutions:**
- Install the extension in Inkscape
- Check extension directory permissions
- Restart the MCP server
- Verify extension ID

### Extension Execution Failed

**Error:** `Extension execution failed`

**Solutions:**
- Check extension parameters
- Verify input file compatibility
- Review extension documentation
- Try with simpler parameters

## Platform-Specific Issues

### Windows Issues

**Common Problems:**
- PATH environment variable not set
- Permission issues with temp directories
- Inkscape GUI/CLI profile lock conflict (see below)

**Solutions:**
- Add Inkscape to system PATH
- Run as administrator if needed

---

### Inkscape GUI and CLI conflict on Windows (profile lock)

**Symptom:** CLI tool calls time out or hang when Inkscape GUI is open. `inkscape_system(status)` shows `inkscape.available: false` even though Inkscape is installed and running.

**Cause:** On Windows, Inkscape locks `preferences.xml` in the user profile directory (`%APPDATA%\inkscape`) when the GUI is open. Any CLI invocation (`inkscape --export-filename=...`) attempts to read and write the same profile on startup and blocks waiting for the lock, causing the MCP tool call to time out. This is an Inkscape architectural limitation, not a bug in inkscape-mcp.

**Fix — isolated CLI profile (recommended):**

Set `INKSCAPE_PROFILE_DIR` to a separate directory in the inkscape-mcp server environment. The CLI gets its own profile that the GUI never touches. In your Claude Desktop config (`claude_desktop_config.json`), add to the `inkscape-mcp` env block:

```json
"INKSCAPE_PROFILE_DIR": "D:/Dev/repos/inkscape-mcp/inkscape-profile"
```

The directory is created automatically on first CLI run. GUI and CLI then coexist without conflicts.

**Alternative — close the GUI before CLI ops:**

Not practical for interactive use, but works if you only need CLI batch processing and have no need for the GUI simultaneously.

**Not recommended:** Running the GUI in a VM (VirtualBox, Windows Sandbox) to isolate it. This works in principle but is wildly overcomplicated for a profile directory problem.

---

### macOS Issues

**Common Problems:**
- Homebrew installation conflicts
- Permission issues with system directories

**Solutions:**
- Install via Homebrew: `brew install inkscape`
- Check /usr/local permissions
- Use absolute paths

### Linux Issues

**Common Problems:**
- Missing system dependencies
- Display server conflicts
- Library version conflicts

**Solutions:**
- Install required packages: `sudo apt install inkscape`
- Use `--batch-process` flag
- Check library dependencies

## Performance Issues

### Slow Operations

**Causes:**
- Large file sizes
- Complex operations
- System resource constraints
- Network latency (for AI operations)

**Solutions:**
- Reduce file sizes
- Use simpler operations
- Increase system resources
- Cache frequent operations

### Memory Issues

**Error:** `Out of memory`

**Solutions:**
- Reduce concurrent operations in config
- Process files in smaller batches
- Close other applications
- Add more RAM or use smaller files

### High CPU Usage

**Causes:**
- Multiple concurrent operations
- Complex AI generation
- Large file processing

**Solutions:**
- Reduce `max_concurrent_processes`
- Use lower quality settings
- Process sequentially instead of parallel

## Configuration Issues

### Config Not Loaded

**Problem:** Configuration changes not applied

**Solutions:**
- Check YAML syntax
- Use absolute paths
- Restart the server
- Verify file permissions

### Invalid Configuration

**Error:** `Configuration validation failed`

**Solutions:**
- Check YAML indentation
- Verify parameter types
- Review documentation for valid values
- Use default configuration as template

## Network Issues

### Connection Refused

**Error:** `Connection to MCP server failed`

**Solutions:**
- Check if server is running
- Verify port configuration
- Check firewall settings
- Use correct server URL

### Timeout Issues

**Problem:** Network operations timeout

**Solutions:**
- Increase timeout values
- Check network connectivity
- Reduce request complexity
- Use local operations when possible

## Logging and Debugging

### Enable Debug Logging

Add to configuration:
```yaml
logging:
  level: DEBUG
  file: inkscape-mcp.log
```

### Check Logs

Common log locations:
- Console output (when running directly)
- System log files
- Application-specific log directory

### Common Debug Steps

1. Enable verbose logging
2. Check system resources
3. Verify file permissions
4. Test with minimal example
5. Check network connectivity
6. Review error messages carefully

## Getting Help

### Documentation Resources
- [README.md](README.md) - Basic usage
- [USAGE.md](USAGE.md) - Detailed usage examples
- [API.md](API.md) - Complete API reference
- [ARCHITECTURE.md](ARCHITECTURE.md) - Technical details

### Community Support
- GitHub Issues for bug reports
- GitHub Discussions for questions
- Documentation wiki for tutorials

### Diagnostic Information

When reporting issues, include:
- Operating system and version
- Python version
- Inkscape version
- Full error message and stack trace
- Configuration file (without sensitive data)
- Steps to reproduce the issue
