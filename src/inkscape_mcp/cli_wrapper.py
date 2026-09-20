"""
Minimal Inkscape CLI Wrapper for essential vector graphics operations.

This module provides core Inkscape command-line functionality for MCP operations.
"""

import asyncio
import logging
import math
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from PIL import Image

from inkscape_mcp.utils.inkscape_actions import validate_actions

logger = logging.getLogger(__name__)


class InkscapeCliError(Exception):
    """Base exception for Inkscape CLI operations."""

    pass


class InkscapeTimeoutError(InkscapeCliError):
    """Exception for Inkscape operation timeouts."""

    pass


class InkscapeExecutionError(InkscapeCliError):
    """Exception for Inkscape execution failures."""

    pass


class InkscapeCliWrapper:
    """
    Minimal Inkscape CLI wrapper for essential vector graphics operations.
    """

    def __init__(self, config):
        """
        Initialize wrapper with config.
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        self._slots = asyncio.Semaphore(getattr(config, "max_concurrent_processes", 3))
        self._gui_lock = asyncio.Lock()

        # Basic validation
        if not hasattr(config, "inkscape_executable") or not config.inkscape_executable:
            raise InkscapeCliError("Inkscape executable not configured")

        if not Path(config.inkscape_executable).exists():
            raise InkscapeCliError(f"Inkscape executable not found: {config.inkscape_executable}")

    async def export_file(
        self,
        input_path: str,
        output_path: str,
        export_type: str = "png",
        dpi: int = 300,
        export_area: str = "drawing",
        timeout: int | None = None,
    ) -> str:
        """
        Export SVG file to raster or vector format using Inkscape CLI.

        Args:
            input_path: Input SVG file path
            output_path: Output file path
            export_type: Export format (png, pdf, eps, svg)
            dpi: Resolution for raster exports (ignored for vector formats)
            export_area: Export area (drawing, page, or custom coordinates)
            timeout: Operation timeout in seconds

        Returns:
            str: Inkscape output

        Raises:
            InkscapeExecutionError: If execution fails
            InkscapeTimeoutError: If operation times out
        """
        timeout = self._timeout(timeout)
        input_path = self._input_path(input_path)
        export_type = export_type.lower()
        if export_type not in {"svg", "png", "ps", "eps", "pdf", "emf", "wmf", "xaml"}:
            raise InkscapeExecutionError(f"Unsupported Inkscape export format: {export_type}")
        if not math.isfinite(dpi) or dpi <= 0:
            raise InkscapeExecutionError("Export DPI must be positive and finite")
        args = [self.config.inkscape_executable, "--export-type", export_type]
        if export_type == "png":
            args.extend(["--export-dpi", str(dpi)])
        if export_area in {"drawing", "page"}:
            args.append(f"--export-area-{export_area}")
        elif export_area.startswith("custom:"):
            coords = export_area.split(":", 1)[1]
            try:
                x0, y0, x1, y1 = map(float, coords.split(":"))
                valid = all(math.isfinite(v) for v in (x0, y0, x1, y1)) and x1 > x0 and y1 > y0
            except ValueError:
                valid = False
            if not valid:
                raise InkscapeExecutionError("Invalid custom export area: expected x0:y0:x1:y1")
            args.extend(["--export-area", coords])
        else:
            raise InkscapeExecutionError(f"Unknown export area: {export_area}")
        with self._export_target(output_path, suffix=f".{export_type}") as target:
            args.extend([f"--export-filename={target}", input_path])
            result = await self._execute_command(args, timeout)
        return result

    async def query_object(
        self,
        input_path: str,
        object_id: str,
        query_type: str = "bbox",
        timeout: int | None = None,
    ) -> str:
        """
        Query object properties from SVG file using Inkscape CLI.

        Args:
            input_path: Input SVG file path
            object_id: ID of object to query
            query_type: Type of query (bbox, x, y, width, height, all)
            timeout: Operation timeout in seconds

        Returns:
            str: Query result output

        Raises:
            InkscapeExecutionError: If execution fails
            InkscapeTimeoutError: If operation times out
        """
        timeout = self._timeout(timeout)
        if query_type not in {"bbox", "x", "y", "width", "height", "all"}:
            raise InkscapeExecutionError(f"Unknown query type: {query_type}")
        args = [self.config.inkscape_executable, "--query-id", object_id]
        if query_type == "bbox":
            args.extend(["--query-x", "--query-y", "--query-width", "--query-height"])
        elif query_type == "all":
            args.append("--query-all")
        else:
            args.append(f"--query-{query_type}")
        args.append(self._input_path(input_path))
        result = await self._execute_command(args, timeout)
        if query_type == "all":
            for line in result.splitlines():
                ident, separator, coordinates = line.partition(",")
                if separator and ident == object_id:
                    return coordinates
            raise InkscapeExecutionError(f"Object not found: {object_id}")
        if query_type == "bbox":
            values = result.replace(",", " ").split()
            if len(values) != 4:
                raise InkscapeExecutionError(f"Expected four bounding-box coordinates: {result!r}")
            try:
                if not all(math.isfinite(float(v)) for v in values):
                    raise ValueError
            except ValueError as exc:
                raise InkscapeExecutionError(
                    "Inkscape returned invalid bounding-box coordinates"
                ) from exc
            return ",".join(values)
        return result

    async def execute_verbs(
        self,
        input_path: str,
        verbs: list[str],
        output_path: str | None = None,
        timeout: int | None = None,
    ) -> str:
        """
        Execute Inkscape verbs (actions) on an SVG file.

        Args:
            input_path: Input SVG file path
            verbs: List of Inkscape verb IDs to execute
            output_path: Optional output path (will overwrite input if None)
            timeout: Operation timeout in seconds

        Returns:
            str: Inkscape output

        Raises:
            InkscapeExecutionError: If execution fails
            InkscapeTimeoutError: If operation times out
        """
        # --verb was removed in modern Inkscape. Preserve common legacy names
        # through the supported Actions API; unknown names fail explicitly.
        aliases = {
            "EditSelectAll": "select-all",
            "ObjectToPath": "object-to-path",
            "SelectionUnion": "path-union",
            "SelectionDiff": "path-difference",
            "SelectionIntersect": "path-intersection",
            "SelectionCombine": "path-combine",
            "SelectionBreakApart": "path-break-apart",
            "SelectionSimplify": "path-simplify",
        }
        actions = [aliases.get(verb, verb) for verb in verbs]
        return await self._execute_actions(input_path, actions, output_path, timeout)

    async def _execute_actions(
        self,
        input_path: str,
        actions: list[str],
        output_path: str | None = None,
        timeout: int | None = None,
        *,
        vacuum_defs: bool = False,
    ) -> str:
        """Run a file-based action sequence, committing an export only on success."""
        timeout = self._timeout(timeout)
        input_path = self._input_path(input_path)
        try:
            actions_to_run = validate_actions(actions)
        except ValueError as exc:
            raise InkscapeExecutionError(str(exc)) from exc
        args = [
            self.config.inkscape_executable,
            f"--app-id-tag=inkscape-mcp-{uuid4().hex}",
            "--batch-process",
            input_path,
        ]
        if vacuum_defs:
            args.append("--vacuum-defs")
        if output_path:
            # The wrapper owns the export path and document lifetime. Embedded
            # filenames bypass staging and semicolons in paths become actions.
            for action in actions_to_run:
                name = action.partition(":")[0].removeprefix("app.")
                if name in {
                    "file-open",
                    "file-new",
                    "file-save",
                    "file-save-as",
                    "file-close",
                    "export-filename",
                    "export-use-hints",
                    "export-latex",
                    "export-id",
                    "export-page",
                    "quit",
                }:
                    raise InkscapeExecutionError(
                        f"{name} cannot be used with a managed output_path; "
                        "use a separate file-based operation"
                    )
            # --export-filename already triggers an export after the actions.
            # export-do would export twice; Inkscape mutates its filename during
            # the first export and can report an invalid type on the second.
            actions_to_run = [action for action in actions_to_run if action != "export-do"]
            export_type = Path(output_path).suffix.lstrip(".").lower()
            for action in actions_to_run:
                if action.startswith("export-type:"):
                    export_type = action.partition(":")[2].lower()
            if export_type not in {"svg", "png", "ps", "eps", "pdf", "emf", "wmf", "xaml"}:
                raise InkscapeExecutionError(f"Unsupported Inkscape export format: {export_type}")
            with self._export_target(output_path, suffix=f".{export_type}") as target:
                result = await self._execute_command(
                    [
                        *args,
                        f"--export-type={export_type}",
                        f"--actions={';'.join(actions_to_run)}",
                        f"--export-filename={target}",
                    ],
                    timeout,
                )
            return result
        args.append(f"--actions={';'.join(actions_to_run)}")
        return await self._execute_command(args, timeout)

    async def execute_actions(
        self,
        input_path: str,
        actions: list[str],
        output_path: str | None = None,
        timeout: int | None = None,
        *,
        vacuum_defs: bool = False,
    ) -> str:
        """Execute supported Inkscape actions in an isolated batch process."""
        return await self._execute_actions(
            input_path, actions, output_path, timeout, vacuum_defs=vacuum_defs
        )

    def _timeout(self, timeout: int | None) -> float:
        value = self.config.process_timeout if timeout is None else timeout
        if not math.isfinite(value) or value <= 0:
            raise InkscapeExecutionError("Timeout must be positive and finite")
        return value

    @staticmethod
    def _input_path(input_path: str) -> str:
        path = Path(input_path).expanduser().resolve()
        if not path.is_file():
            raise InkscapeExecutionError(f"Input file not found: {path}")
        return str(path)

    @staticmethod
    @contextmanager
    def _export_target(output_path: str, *, suffix: str | None = None):
        """Stage beside the destination so os.replace is atomic on its filesystem."""
        destination = Path(output_path).expanduser().resolve()
        temporary = None
        try:
            fd, name = tempfile.mkstemp(
                prefix="inkscape-mcp-", suffix=suffix or destination.suffix, dir=destination.parent
            )
            os.close(fd)
            temporary = Path(name)
            yield temporary
            if not temporary.is_file() or temporary.stat().st_size == 0:
                raise InkscapeExecutionError("Inkscape did not produce a non-empty export")
            if temporary.suffix.lower() == ".svg":
                try:
                    root = ET.parse(temporary).getroot()  # noqa: S314 - locally generated output
                    if root.tag not in {"svg", "{http://www.w3.org/2000/svg}svg"}:
                        raise ValueError("root element is not SVG")
                except (ET.ParseError, ValueError) as exc:
                    raise InkscapeExecutionError(f"Inkscape produced invalid SVG: {exc}") from exc
            elif temporary.suffix.lower() == ".png":
                try:
                    with Image.open(temporary) as exported:
                        if exported.format != "PNG":
                            raise ValueError("output is not PNG")
                        exported.verify()
                except (OSError, ValueError, SyntaxError) as exc:
                    raise InkscapeExecutionError(f"Inkscape produced invalid PNG: {exc}") from exc
            elif temporary.suffix.lower() == ".pdf":
                with temporary.open("rb") as exported:
                    header = exported.read(5)
                    exported.seek(max(0, temporary.stat().st_size - 1024))
                    trailer = exported.read()
                if header != b"%PDF-" or not trailer.rstrip().endswith(b"%%EOF"):
                    raise InkscapeExecutionError("Inkscape produced an incomplete PDF")
            if destination.exists():
                temporary.chmod(destination.stat().st_mode & 0o777)
            temporary.replace(destination)
        except OSError as exc:
            raise InkscapeExecutionError(f"Cannot export to {destination}: {exc}") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    async def get_document_info(self, input_path: str, timeout: int | None = None) -> str:
        """
        Get document information and metadata from SVG file.

        Args:
            input_path: Input SVG file path
            timeout: Operation timeout in seconds

        Returns:
            str: Document information output

        Raises:
            InkscapeExecutionError: If execution fails
            InkscapeTimeoutError: If operation times out
        """
        timeout = self._timeout(timeout)

        # Build command arguments for document info
        cmd_args = [
            self.config.inkscape_executable,
            "--query-all",  # Get all object information
            input_path,
        ]

        return await self._execute_command(cmd_args, timeout)

    async def _execute_command(self, cmd_args: list[str], timeout: int) -> str:
        # Inkscape's GUI bridge uses global mutable state and a shared exchange
        # file. Serialize live commands so their start/end pairs cannot overlap.
        if "--active-window" in cmd_args or "-q" in cmd_args:
            async with self._gui_lock:
                return await self._run_command(cmd_args, timeout)
        return await self._run_command(cmd_args, timeout)

    async def _run_command(self, cmd_args: list[str], timeout: int) -> str:
        """Run an isolated process, returning only stdout and reaping on interruption."""
        timeout = self._timeout(timeout)
        command = list(map(str, cmd_args))
        try:
            for i, arg in enumerate(command):
                if arg.startswith("--actions="):
                    validate_actions(arg.partition("=")[2])
                elif arg == "--actions":
                    if i + 1 == len(command):
                        raise ValueError("--actions requires an action argument")
                    validate_actions(command[i + 1])
                elif arg == "--actions-file" or arg.startswith("--actions-file="):
                    raise ValueError(
                        "Use explicit actions so they can be validated before execution"
                    )
        except ValueError as exc:
            raise InkscapeExecutionError(str(exc)) from exc
        environment = self._get_environment()
        if "--active-window" not in command and "-q" not in command:
            tag = next(
                (arg.partition("=")[2] for arg in command if arg.startswith("--app-id-tag=")),
                None,
            )
            if tag is None and "--app-id-tag" in command:
                index = command.index("--app-id-tag")
                if index + 1 < len(command):
                    tag = command[index + 1]
            if tag is None:
                tag = f"inkscape-mcp-{uuid4().hex}"
                command.insert(1, f"--app-id-tag={tag}")
            # Inkscape probes the default D-Bus application during construction,
            # before reading --app-id-tag. Concurrent launches can race in that
            # version check and abort. Set the same identity before construction.
            environment["INKSCAPE_APP_ID_TAG"] = tag
            # Queries and plain exports already terminate without a GUI.
            # --batch-process is only needed for actions and can otherwise
            # initialize the desktop unnecessarily on machines with DISPLAY.
            has_actions = any(arg == "--actions" or arg.startswith("--actions=") for arg in command)
            if has_actions and "--batch-process" not in command:
                command.insert(1, "--batch-process")
        async with self._slots:
            process = None
            try:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=environment,
                )
                try:
                    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
                except (Exception, asyncio.CancelledError) as exc:
                    # Reap on pipe failures as well as timeouts/cancellation.
                    # Repeated cancellations must not release the process slot
                    # or delete a staged export while its child is still alive.
                    await self._terminate_and_reap(process)
                    if isinstance(exc, TimeoutError):
                        raise InkscapeTimeoutError(
                            f"Command timed out after {timeout} seconds"
                        ) from exc
                    raise
                output = stdout.decode("utf-8", errors="replace")
                diagnostics = stderr.decode("utf-8", errors="replace")
                # Several CLI errors (including unknown actions) still exit with
                # status zero. Benign GTK/font warnings must not corrupt queries.
                fatal = re.search(
                    r"(?im)(?:^|\n).*?(?:parse_actions:.*(?:could not find|invalid)|"
                    r"unknown (?:option|action)|unable to (?:open|export)|"
                    r"unknown export type|no export type specified|"
                    r"failed to (?:load|open|save|export)|(?:^|\s)error:|"
                    r"cannot be opened|failed to create document|tracing failed|"
                    r"did not find object with id|"
                    r"action:[^\n]*(?:selection empty|expected argument|parsing arguments failed)|"
                    r"no active desktop to run|active window is not available on macOS|"
                    r"emergency save activated|segmentation fault)",
                    diagnostics,
                )
                # The live-window bridge also writes failures to stdout while
                # returning status zero. Match actual diagnostic lines here:
                # query IDs and SVG text may legitimately contain error words.
                fatal_output = re.search(
                    r"(?im)^\s*(?:"
                    r"no active desktop to run\b[^\n]*|"
                    r"active window is not available on macOS\b[^\n]*|"
                    r"(?:InkscapeApplication::)?parse_actions:[^\n]*(?:could not find|invalid)[^\n]*|"
                    r"action:[^\n]*(?:selection empty|expected argument|parsing arguments failed)[^\n]*"
                    r")$",
                    output,
                )
                if process.returncode != 0 or fatal or fatal_output:
                    detail = "\n".join(
                        part.strip()[-4000:] for part in (diagnostics, output) if part.strip()
                    )
                    raise InkscapeExecutionError(
                        f"Inkscape command failed with return code {process.returncode}: {detail}"
                    )
                if diagnostics.strip():
                    self.logger.warning("Inkscape diagnostics: %s", diagnostics.strip()[-2000:])
                return output
            except FileNotFoundError as exc:
                raise InkscapeExecutionError(
                    f"Inkscape executable not found: {self.config.inkscape_executable}"
                ) from exc
            except InkscapeCliError:
                raise
            except Exception as exc:
                raise InkscapeExecutionError(f"Command execution failed: {exc}") from exc

    @staticmethod
    async def _terminate_and_reap(process: asyncio.subprocess.Process) -> None:
        async def cleanup() -> None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            try:
                await process.communicate()
            finally:
                await process.wait()

        cleanup_task = asyncio.create_task(cleanup())
        cancelled = False
        while not cleanup_task.done():
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                cancelled = True
        cleanup_task.result()
        if cancelled:
            raise asyncio.CancelledError

    def _get_environment(self) -> dict[str, str]:
        """
        Get environment variables for subprocess execution.
        """
        env = os.environ.copy()

        # Ensure UTF-8 encoding
        env["LANG"] = "C.UTF-8"
        env["LC_ALL"] = "C.UTF-8"

        return env


# Backward compatibility alias for legacy code
GimpCliWrapper = InkscapeCliWrapper
