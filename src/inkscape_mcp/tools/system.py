"""System diagnostics, action discovery, and addressed live document workflows.

Public operations are exposed by the FastMCP wrapper in main.py.
See docs/TOOLS.md for parameters, platform requirements, and limitations.
"""

import logging
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from typing import Literal

from pydantic import BaseModel

from .. import __version__
from ..utils.execution_mode import describe_execution_mode
from ..utils.telemetry import set_execution_mode

logger = logging.getLogger(__name__)


class SystemResult(BaseModel):
    """Result model for system operations."""

    success: bool
    operation: str
    message: str
    data: dict[str, Any]
    execution_time_ms: float
    error: str = ""


async def inkscape_system(
    operation: Literal[
        "status",
        "help",
        "diagnostics",
        "version",
        "config",
        "execution_mode",
        "hands_in_command",
        "active_document",
        "insert_svg",
        "draw_test",
        "install_live_extension",
        "save_document",
        "save_copy",
        "close_document",
        "list_actions",
        "list_documents",
        "open_document",
        "new_document",
        "list_extensions",
        "execute_extension",
        "self_terminate",
    ],
    extension_id: str | None = None,
    _extension_params: dict[str, Any] | None = None,
    _input_file: str | None = None,
    _output_file: str | None = None,
    action: str = "",
    svg_content: str = "",
    text: str = "Prova MCP OK",
    search: str = "",
    limit: int = 100,
    offset: int = 0,
    input_path: str = "",
    output_path: str = "",
    session_id: str = "desktop",
    cli_wrapper: Any = None,
    config: Any = None,
) -> dict[str, Any]:
    """Inkscape system operations portmanteau tool."""
    start_time = time.time()

    try:
        if operation in {"list_documents", "open_document", "new_document"}:
            from ..utils import document_sessions

            if operation == "list_documents":
                data = await document_sessions.list_documents(cli_wrapper, config)
                message = f"Found {data['count']} Inkscape document sessions"
            elif operation == "open_document":
                data = await document_sessions.open_document(input_path, cli_wrapper, config)
                message = "Opened SVG in a managed Inkscape document session"
            else:
                data = await document_sessions.new_document(output_path, cli_wrapper, config)
                message = "Created SVG and opened a managed Inkscape document session"
            return SystemResult(
                success=True,
                operation=operation,
                message=message,
                data=data,
                execution_time_ms=(time.time() - start_time) * 1000,
            ).model_dump()

        if operation == "list_actions":
            from ..utils.action_catalog import list_actions

            data = await list_actions(
                cli_wrapper=cli_wrapper, config=config, search=search, limit=limit, offset=offset
            )
            return SystemResult(
                success=True,
                operation=operation,
                message=f"Retrieved {data['returned']} of {data['matched_actions']} matching CLI actions",
                data=data,
                execution_time_ms=(time.time() - start_time) * 1000,
            ).model_dump()

        if operation == "status":
            # Get server and Inkscape status
            inkscape_available = False
            inkscape_version = "unknown"

            try:
                if config and config.inkscape_executable and cli_wrapper:
                    result = await cli_wrapper._execute_command(
                        [str(config.inkscape_executable), "--version"], config.process_timeout
                    )
                    inkscape_available = True
                    inkscape_version = result.strip().split("\n")[0] if result else "unknown"
            except Exception as exc:
                logger.warning("Inkscape version probe failed: %s", exc)

            return SystemResult(
                success=True,
                operation="status",
                message="Retrieved system status",
                data={
                    "server": {
                        "name": "Inkscape MCP Server",
                        "version": __version__,
                        "status": "running",
                    },
                    "inkscape": {
                        "available": inkscape_available,
                        "version": inkscape_version,
                        "executable": str(config.inkscape_executable) if config else None,
                    },
                    "tools": {
                        "file": "available",
                        "vector": "available",
                        "analysis": "available",
                        "render": "available",
                        "validation": "available",
                        "fleet": "available",
                        "fab_art": "available",
                        "sim_art": "available",
                        "system": "available",
                    },
                },
                execution_time_ms=(time.time() - start_time) * 1000,
            ).model_dump()

        elif operation == "execution_mode":
            mode_data = await describe_execution_mode(cli_wrapper=cli_wrapper, config=config)
            set_execution_mode(mode_data.get("mode") == "hands_in")
            return SystemResult(
                success=True,
                operation="execution_mode",
                message="Execution mode guidance for agents",
                data=mode_data,
                execution_time_ms=(time.time() - start_time) * 1000,
            ).model_dump()

        elif operation == "install_live_extension":
            from inkscape_mcp.utils.live_extension import install_live_extension

            data = install_live_extension(config)
            return SystemResult(
                success=True,
                operation=operation,
                message="Installed the live editing extension; restart existing Inkscape windows once",
                data=data,
                execution_time_ms=(time.time() - start_time) * 1000,
            ).model_dump()

        elif operation in {"save_document", "save_copy", "close_document"}:
            from inkscape_mcp.utils.document_lifecycle import document_lifecycle

            data = await document_lifecycle(operation, session_id, output_path, cli_wrapper, config)
            return SystemResult(
                success=True,
                operation=operation,
                message=data["message"],
                data=data,
                execution_time_ms=(time.time() - start_time) * 1000,
            ).model_dump()

        elif operation in {"active_document", "insert_svg", "draw_test"}:
            from inkscape_mcp.utils import live_document

            if cli_wrapper is None or config is None:
                raise ValueError("Inkscape CLI is not configured")
            if operation == "active_document":
                data = await live_document.active_document(cli_wrapper, config, session_id)
                message = "Read the active Inkscape document, including unsaved content"
            else:
                content = (
                    live_document.build_test_svg(text) if operation == "draw_test" else svg_content
                )
                data = await live_document.insert_svg(content, cli_wrapper, config, session_id)
                message = (
                    "Inserted editable objects and verified them in the active Inkscape document"
                )
            return SystemResult(
                success=True,
                operation=operation,
                message=message,
                data=data,
                execution_time_ms=(time.time() - start_time) * 1000,
            ).model_dump()

        elif operation == "hands_in_command":
            from inkscape_mcp.utils.inkscape_actions import validate_actions

            if not action or not validate_actions(action):
                return SystemResult(
                    success=False,
                    operation="hands_in_command",
                    message="action parameter is required (e.g. 'select-all;object-flip-horizontally')",
                    data={},
                    execution_time_ms=0,
                    error="ValueError",
                ).model_dump()

            try:
                # Never allow callers to corrupt the bridge's internal start/end
                # state; it is managed by --active-window itself (upstream #4765).
                validate_actions(action)
                if cli_wrapper is None or config is None or not config.inkscape_executable:
                    raise ValueError("Inkscape CLI is not configured")
                requested_session = session_id or "desktop"
                command = [str(config.inkscape_executable), "--active-window"]
                if requested_session != "desktop":
                    from inkscape_mcp.utils.document_sessions import get_session

                    target = await get_session(requested_session, cli_wrapper, config)
                    if not target.get("managed") or not target.get("app_id_tag"):
                        raise ValueError(
                            "The requested managed session has no application identifier"
                        )
                    command.append(f"--app-id-tag={target['app_id_tag']}")
                # The tagged active-window command reaches only this managed
                # instance. Unknown/closed sessions must never fall back to the
                # untagged desktop; legacy desktop CLI remains cross-platform.
                command.extend(["--actions", action])
                result = await cli_wrapper._execute_command(
                    command,
                    config.process_timeout,
                )
                return SystemResult(
                    success=True,
                    operation="hands_in_command",
                    message=f"Sent action to active Inkscape window: {action[:120]}",
                    data={
                        "action": action,
                        "session_id": requested_session,
                        "response": result.strip()[:500],
                    },
                    execution_time_ms=(time.time() - start_time) * 1000,
                ).model_dump()
            except Exception as exc:
                return SystemResult(
                    success=False,
                    operation="hands_in_command",
                    message=f"Hands-in command failed: {exc}. Is Inkscape GUI running?",
                    data={
                        "action": action,
                        "session_id": session_id or "desktop",
                        "hint": "Keep the target window open and use its exact session_id from list_documents",
                    },
                    execution_time_ms=0,
                    error=str(exc),
                ).model_dump()

        elif operation == "version":
            # Get version information
            return SystemResult(
                success=True,
                operation="version",
                message="Retrieved version information",
                data={
                    "server": f"Inkscape MCP Server v{__version__}",
                    "version": __version__,
                    "protocol": "FastMCP 3.2+",
                    "architecture": "Portmanteau tools with batch operations and managed document sessions",
                    "inkscape_required": "1.0+ (1.2+ recommended for Actions API)",
                },
                execution_time_ms=(time.time() - start_time) * 1000,
            ).model_dump()

        elif operation == "diagnostics":
            # Run basic diagnostic checks
            checks = {
                "config_loaded": config is not None,
                "cli_wrapper_available": cli_wrapper is not None,
                "inkscape_executable_set": bool(config and config.inkscape_executable)
                if config
                else False,
            }

            return SystemResult(
                success=True,
                operation="diagnostics",
                message="Ran diagnostic checks",
                data={
                    "checks": checks,
                    "all_passed": all(checks.values()),
                    "issues": [k for k, v in checks.items() if not v],
                },
                execution_time_ms=(time.time() - start_time) * 1000,
            ).model_dump()

        elif operation == "list_extensions":
            from ..utils.live_extension import extension_directory

            # Scan Inkscape extensions directories for .inx files
            extensions: list[dict[str, str]] = []
            ext_dirs: list[str] = []
            if config and config.inkscape_executable:
                base = Path(str(config.inkscape_executable)).parent.parent
                ext_dirs.append(str(base / "share" / "inkscape" / "extensions"))
                ext_dirs.append(str(Path.home() / ".config" / "inkscape" / "extensions"))
                ext_dirs.append(
                    str(Path.home() / "AppData" / "Roaming" / "inkscape" / "extensions")
                )
            ext_dirs.append(str(extension_directory().parent))
            ext_dirs = list(dict.fromkeys(ext_dirs))
            for d in ext_dirs:
                dp = Path(d)
                if dp.is_dir():
                    for inx in sorted(dp.rglob("*.inx")):
                        try:
                            root = ET.parse(inx).getroot()
                            fields = {
                                child.tag.rsplit("}", 1)[-1]: (child.text or "").strip()
                                for child in root
                            }
                            name = fields.get("name") or fields.get("_name")
                            if name:
                                extensions.append(
                                    {
                                        "id": fields.get("id") or inx.stem,
                                        "name": name,
                                        "path": str(inx),
                                    }
                                )
                        except (OSError, ET.ParseError) as exc:
                            logger.debug("Skipping unreadable extension %s: %s", inx, exc)
            return SystemResult(
                success=True,
                operation="list_extensions",
                message=f"Found {len(extensions)} extensions in {len(ext_dirs)} directories",
                data={
                    "extensions": extensions,
                    "total_count": len(extensions),
                    "source_dirs": ext_dirs,
                },
                execution_time_ms=(time.time() - start_time) * 1000,
            ).model_dump()

        elif operation == "execute_extension":
            # Extension system disabled - plugins directory removed
            if not extension_id:
                return SystemResult(
                    success=False,
                    operation="execute_extension",
                    message="Extension ID is required",
                    error="Missing extension_id parameter",
                    execution_time_ms=(time.time() - start_time) * 1000,
                ).model_dump()

            return SystemResult(
                success=False,
                operation="execute_extension",
                message=f"Extension system disabled - cannot execute {extension_id}",
                error="Extension system temporarily disabled",
                data={"note": "Extension system temporarily disabled"},
                execution_time_ms=(time.time() - start_time) * 1000,
            ).model_dump()

        elif operation == "help":
            # Provide help information
            help_info = {
                "server": "Inkscape MCP Server",
                "description": "Professional vector graphics and SVG editing through Model Context Protocol",
                "tools": [
                    "generate_svg: AI-powered SVG generation from natural language descriptions",
                    "inkscape_file: Basic file operations (load, save, convert, info, validate, list_formats)",
                    "inkscape_vector: Advanced vector operations (trace, boolean, optimize, render_preview, etc.)",
                    "inkscape_render: Agent vision exports (export_preview, export_multi_dpi, get_document_summary)",
                    "inkscape_analysis: Document analysis (quality, statistics, validate, objects, dimensions, structure)",
                    "inkscape_system: System operations (status, execution_mode, help, diagnostics, version, config, self_terminate)",
                ],
                "getting_started": [
                    "Ensure Inkscape 1.0+ is installed",
                    "inkscape_system operation=execution_mode for Hands-In vs batch guidance",
                    "inkscape_render operation=export_preview for agent vision loops",
                    "Use inkscape_analysis operation=objects before ID-based vector edits",
                ],
            }

            return SystemResult(
                success=True,
                operation="help",
                message="Retrieved help information",
                data=help_info,
                execution_time_ms=(time.time() - start_time) * 1000,
            ).model_dump()

        elif operation == "self_terminate":
            import os

            logger.warning("Self-termination requested by agent")
            os._exit(0)

        elif operation == "config":
            # View configuration
            config_data = {}
            if config:
                config_data = {
                    "inkscape_executable": str(config.inkscape_executable)
                    if config.inkscape_executable
                    else None,
                    "process_timeout": config.process_timeout
                    if hasattr(config, "process_timeout")
                    else None,
                    "max_concurrent_processes": config.max_concurrent_processes
                    if hasattr(config, "max_concurrent_processes")
                    else None,
                }

            return SystemResult(
                success=True,
                operation="config",
                message="Retrieved configuration",
                data=config_data,
                execution_time_ms=(time.time() - start_time) * 1000,
            ).model_dump()

        else:
            return SystemResult(
                success=False,
                operation=operation,
                message=f"Unknown operation: {operation}",
                data={},
                execution_time_ms=(time.time() - start_time) * 1000,
                error="ValueError",
            ).model_dump()

    except Exception as e:
        return SystemResult(
            success=False,
            operation=operation,
            message=f"System operation failed: {e}",
            data={},
            execution_time_ms=(time.time() - start_time) * 1000,
            error=str(e),
        ).model_dump()
