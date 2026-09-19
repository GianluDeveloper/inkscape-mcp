"""
Inkscape MCP Server - FastMCP 3.1+ portmanteau entry point.

Exposes MCP tools that shell out to the Inkscape CLI, optional heraldry and
agentic (sampling) tools, REST `/api/*` when HTTP transport is used, and
registered MCP prompts/resources (see prompts_resources.py).
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any
from typing import Literal

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .config import InkscapeConfig
from .config import load_config
from .inkscape_detector import InkscapeDetector
from .logging_config import setup_logging
from .mcp_tool_types import InkscapeAnalysisOperation
from .mcp_tool_types import InkscapeFabArtOperation
from .mcp_tool_types import InkscapeFileOperation
from .mcp_tool_types import InkscapeFleetOperation
from .mcp_tool_types import InkscapeRenderOperation
from .mcp_tool_types import InkscapeSimArtOperation
from .mcp_tool_types import InkscapeSystemOperation
from .mcp_tool_types import InkscapeValidationOperation
from .mcp_tool_types import InkscapeVectorOperation
from .prompts_resources import register_prompts_and_resources
from .tools import inkscape_analysis as inkscape_analysis_tool
from .tools import inkscape_fab_art as inkscape_fab_art_tool
from .tools import inkscape_file as inkscape_file_tool
from .tools import inkscape_fleet as inkscape_fleet_tool
from .tools import inkscape_render as inkscape_render_tool
from .tools import inkscape_sim_art as inkscape_sim_art_tool
from .tools import inkscape_system as inkscape_system_tool
from .tools import inkscape_validation as inkscape_validation_tool
from .tools import inkscape_vector as inkscape_vector_tool
from .tools import list_local_models as list_local_models_tool
from .tools import llm_ops as llm_ops_tool
from .tools.heraldry import register_heraldry_tools
from .transport import run_server_async

# Import agentic workflow tools
try:
    from .agentic import register_agentic_tools

    AGENTIC_TOOLS_AVAILABLE = True
except ImportError:
    register_agentic_tools = None
    AGENTIC_TOOLS_AVAILABLE = False

# Import REST API bridge
try:
    from .app import register_rest_api

    REST_API_AVAILABLE = True
except ImportError:
    register_rest_api = None
    REST_API_AVAILABLE = False

# Import Prefab UI
try:
    from .prefab import register_prefabs

    PREFAB_AVAILABLE = True
except ImportError:
    register_prefabs = None
    PREFAB_AVAILABLE = False

# Configure structured logging
logger = setup_logging(component="main")


class InkscapeMCPServer:
    """Main server class for Inkscape MCP integration."""

    def __init__(self, config_path: Path | None = None):
        """Initialize the Inkscape MCP Server.

        Args:
            config_path: Optional path to configuration file
        """
        self.config = load_config(config_path) if config_path else InkscapeConfig.load_default()
        self.mcp = FastMCP("Inkscape MCP Server")
        self.app = self.mcp  # Add app attribute for ASGI compatibility
        self.tools = {}  # Store tool instances for later reference
        self.logger = logging.getLogger(__name__)
        self.cli_wrapper: Any | None = None

    def _validate_configuration(self) -> bool:
        """Validate server configuration."""
        try:
            required_attrs = ["allowed_directories", "max_file_size_mb"]
            for attr in required_attrs:
                if not hasattr(self.config, attr):
                    logger.error(f"Missing required configuration attribute: {attr}")
                    return False
            return True
        except Exception as e:
            logger.error(f"Configuration validation error: {e}")
            return False

    async def initialize(self) -> bool:
        """Initialize server components and register tools."""
        try:
            logger.info("Initializing Inkscape MCP Server...")

            if not self._validate_configuration():
                return False

            # Initialize Inkscape detector
            self.inkscape_detector = InkscapeDetector()
            inkscape_path = (
                self.config.inkscape_executable
                or self.inkscape_detector.detect_inkscape_installation()
            )

            if inkscape_path:
                logger.info(f"Found Inkscape at: {inkscape_path}")
                self.config.inkscape_executable = str(inkscape_path)

                try:
                    from .cli_wrapper import InkscapeCliWrapper

                    self.cli_wrapper = InkscapeCliWrapper(self.config)
                    logger.info("Initialized Inkscape CLI wrapper")
                except Exception as e:
                    logger.error(f"Failed to initialize Inkscape CLI wrapper: {e}")
                    self.cli_wrapper = None
            else:
                logger.warning("Inkscape not found. Running in limited functionality mode")
                self.cli_wrapper = None

            # Register portmanteau tools
            self._register_portmanteau_tools()

            try:
                register_heraldry_tools(self.mcp, self.cli_wrapper, self.config)
                logger.info("Heraldry tools registered")
            except Exception as e:
                logger.warning("Failed to register heraldry tools: %s", e)

            try:
                register_prompts_and_resources(self.mcp)
                logger.info("MCP prompts and resources registered")
            except Exception as e:
                logger.warning("Failed to register prompts/resources: %s", e)

            # Register agentic workflow tools
            if AGENTIC_TOOLS_AVAILABLE and register_agentic_tools:
                try:
                    register_agentic_tools(self.mcp)
                    logger.info("Agentic workflow tools registered")
                except Exception as e:
                    logger.warning(f"Failed to register agentic tools: {e}")

            # Mount REST API bridge (/api/*)
            if REST_API_AVAILABLE and register_rest_api:
                try:
                    register_rest_api(self.mcp, config=self.config)
                    logger.info("REST API bridge mounted at /api")
                except Exception as e:
                    logger.warning(f"Failed to mount REST API bridge: {e}")

            # Register Prefab UI (FastMCP 3.2 GenerativeUI)
            if PREFAB_AVAILABLE and register_prefabs:
                try:
                    register_prefabs(self.mcp)
                    logger.info("Prefab UI components registered")
                except Exception as e:
                    logger.warning(f"Failed to register Prefab UI: {e}")

            from .utils.telemetry import init_metrics
            from .utils.telemetry import install_tool_call_wrapper
            from .utils.telemetry import metrics_enabled
            from .utils.telemetry import register_metrics_routes
            from .utils.telemetry import start_metrics_server

            logger.info("Calling init_metrics...")
            init_metrics()
            logger.info("Calling install_tool_call_wrapper...")
            install_tool_call_wrapper(self.mcp)
            logger.info("Calling register_metrics_routes...")
            register_metrics_routes(self.mcp)
            logger.info("Calling start_metrics_server (if enabled)...")
            if metrics_enabled():
                start_metrics_server()
            logger.info("initialize() returning True")

            return True

        except Exception as e:
            logger.error(f"Critical error during initialization: {e}", exc_info=True)
            return False

    def _register_portmanteau_tools(self) -> None:
        """Register all portmanteau tools with FastMCP (ToolBench-aligned Literals + annotations)."""

        @self.mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=True,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        async def inkscape_file(
            operation: InkscapeFileOperation,
            input_path: str = "",
            output_path: str = "",
            format: str = "",
        ) -> dict[str, Any]:
            """INKSCAPE_FILE - Load, convert, export, and validate SVG/other files via Inkscape CLI.

            PORTMANTEAU RATIONALE: One tool keeps file I/O discoverable without dozens of
            single-purpose tools; `operation` selects the CLI behavior.

            Operations:
            - load: Read/validate path exists for editing workflows.
            - save: Persist changes (requires paths per server policy).
            - convert: Export to pdf/png/etc. (needs output_path, format).
            - info: Metadata and dimensions.
            - validate: Structural check via CLI query.
            - list_formats: Bounded list of supported export formats (no disk read required).

            Args:
                operation: Must be one of the Literal values (schema-enumerated).
                input_path: Source file; may be empty for list_formats only.
                output_path: Destination for save/convert when applicable.
                format: Target format for convert (e.g. pdf, png).

            Returns:
                Dict with success, operation, message, data, execution_time_ms, and error on failure.

            Errors:
                Missing file, permission denied, Inkscape not found - check message/error; verify
                allowed_directories and INKSCAPE_PATH.
            """
            return await inkscape_file_tool(
                operation=operation,
                input_path=input_path,
                output_path=output_path,
                format=format,
                cli_wrapper=self.cli_wrapper,
                config=self.config,
            )

        @self.mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=True,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        async def inkscape_vector(
            operation: InkscapeVectorOperation,
            input_path: str = "",
            output_path: str = "",
            svg_content: str = "",
            params: dict[str, Any] | None = None,
            element_type: str = "",
            object_id: str = "",
            object_ids: list[str] | None = None,
            select_all: bool = False,
            operation_type: str = "",
            threshold: float = 1.0,
            dpi: int = 96,
        ) -> dict[str, Any]:
            """INKSCAPE_VECTOR - Vector editing, booleans, trace, QR/barcode, path ops, previews.

            PORTMANTEAU RATIONALE: Inkscape exposes many CLI actions; grouping avoids tool explosion.

            Operations include: trace_image, generate_barcode_qr, apply_boolean, path_simplify,
            optimize_svg, scour_svg, render_preview, query_document, measure_object, export_dxf,
            layers_to_files, object_raise/lower, set_document_units, and others (see Literal).

            Args:
                operation: Subcommand; must match InkscapeVectorOperation.
                input_path: Primary document path (some ops may use output-only paths in kwargs).
                output_path: Output file when the operation writes a file.
                svg_content: Complete SVG XML for construct_svg; no sampling is required.
                params: For construct_svg, optional header/body/footer instead of svg_content.
                element_type: Optional descriptive label for construct_svg.
                object_id: Object ID for queries or edits on a single object.
                object_ids: Object IDs for a boolean operation.
                select_all: Select all objects for a boolean operation.
                operation_type: Boolean operation: union, difference, intersection, exclusion.
                threshold: Simplification threshold; native Inkscape uses its configured value.
                dpi: Raster preview resolution.

            Returns:
                Dict with success, message, data or structured results, execution_time_ms, error.

            Errors:
                Unsupported operation, CLI timeout, invalid paths - use inkscape_system(status)
                and confirm Inkscape install.
            """
            return await inkscape_vector_tool(
                operation=operation,
                input_path=input_path,
                output_path=output_path,
                svg_content=svg_content,
                params=params,
                element_type=element_type,
                object_id=object_id,
                object_ids=object_ids,
                select_all=select_all,
                operation_type=operation_type,
                threshold=threshold,
                dpi=dpi,
                cli_wrapper=self.cli_wrapper,
                config=self.config,
            )

        @self.mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        async def inkscape_analysis(
            operation: InkscapeAnalysisOperation, input_path: str
        ) -> dict[str, Any]:
            """INKSCAPE_ANALYSIS - Inspect SVG structure, stats, quality, and dimensions (read-only).

            PORTMANTEAU RATIONALE: Analysis calls are grouped so agents can validate before mutating.

            Operations: quality, statistics, validate, objects, dimensions, structure.

            Args:
                operation: Analysis mode (Literal).
                input_path: SVG file to analyze.

            Returns:
                Dict with success, message, data (bounded per operation), execution_time_ms, error.

            Errors:
                File not found or unreadable SVG - check path and permissions.
            """
            return await inkscape_analysis_tool(
                operation=operation,
                input_path=input_path,
                cli_wrapper=self.cli_wrapper,
                config=self.config,
            )

        @self.mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        async def inkscape_render(
            operation: InkscapeRenderOperation,
            input_path: str = "",
            output_path: str = "",
            dpi: int = 96,
            dpi_list: str = "",
        ) -> dict[str, Any]:
            """INKSCAPE_RENDER - Agent vision exports and document summaries (Phase 1).

            PORTMANTEAU RATIONALE: Vision-loop exports are grouped separately from vector editing.

            Operations:
            - export_preview: PNG preview at dpi (default 96) for agent vision loops.
            - export_multi_dpi: Batch PNG exports (default 96,192,384 or dpi_list CSV).
            - get_document_summary: Statistics + validation snapshot before mutating paths.

            Args:
                operation: Render subcommand (Literal).
                input_path: Source SVG for all operations.
                output_path: Destination PNG; auto-generated under temp_directory when empty.
                dpi: Target DPI for export_preview.
                dpi_list: Comma-separated DPI values for export_multi_dpi.

            Returns:
                Dict with success, message, data, execution_time_ms, error.

            Errors:
                Missing input_path, Inkscape CLI unavailable, invalid dpi_list - see message.
            """
            return await inkscape_render_tool(
                operation=operation,
                input_path=input_path,
                output_path=output_path,
                dpi=dpi,
                dpi_list=dpi_list,
                cli_wrapper=self.cli_wrapper,
                config=self.config,
            )

        @self.mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        async def inkscape_validation(
            operation: InkscapeValidationOperation,
            input_path: str = "",
            max_file_size_mb: int = 10,
            max_dimension: float = 16384,
        ) -> dict[str, Any]:
            """INKSCAPE_VALIDATION - SVG QA checks for Agent Lab and web export pipelines.

            Operations: validate_svg, check_viewbox, check_stroke_fill, check_size_limits,
            audit_web_svg.

            Args:
                operation: Validation mode (Literal).
                input_path: SVG file to validate.
                max_file_size_mb: Size cap for check_size_limits and audit_web_svg.
                max_dimension: Maximum declared width/height in px units.

            Returns:
                Dict with success, message, data metrics, issues[], execution_time_ms, error.
            """
            return await inkscape_validation_tool(
                operation=operation,
                input_path=input_path,
                max_file_size_mb=max_file_size_mb,
                max_dimension=max_dimension,
                cli_wrapper=self.cli_wrapper,
                config=self.config,
            )

        @self.mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=False,
                openWorldHint=True,
            ),
        )
        async def inkscape_fleet(
            operation: InkscapeFleetOperation,
            svg_path: str = "",
            png_path: str = "",
            project_path: str = "",
            output_dir: str = "",
            staging_dir: str = "",
            dpi: int = 192,
            gimp_url: str = "",
            blender_url: str = "",
            unity_url: str = "",
            import_to_blender: bool = False,
            skip_validate: bool = False,
            skip_gimp: bool = False,
            skip_blender_stage: bool = True,
            skip_unity: bool = False,
            target_platform: str = "unity",
        ) -> dict[str, Any]:
            """INKSCAPE_FLEET - Cross-repo handoff (gimp QA, blender SVG, unity sprites).

            Operations: push_gimp_raster, stage_blender_svg, push_unity_sprite,
            build_layer_atlas, run_pipeline, list_staging.
            """
            return await inkscape_fleet_tool(
                operation=operation,
                svg_path=svg_path,
                png_path=png_path,
                project_path=project_path,
                output_dir=output_dir,
                staging_dir=staging_dir,
                dpi=dpi,
                gimp_url=gimp_url,
                blender_url=blender_url,
                unity_url=unity_url,
                import_to_blender=import_to_blender,
                skip_validate=skip_validate,
                skip_gimp=skip_gimp,
                skip_blender_stage=skip_blender_stage,
                skip_unity=skip_unity,
                target_platform=target_platform,
                cli_wrapper=self.cli_wrapper,
                config=self.config,
            )

        @self.mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=False,
                openWorldHint=True,
            ),
        )
        async def inkscape_fab_art(
            operation: InkscapeFabArtOperation,
            input_dir: str = "",
            output_dir: str = "",
            svg_path: str = "",
            png_path: str = "",
            preset_id: str = "gazebo_model_doc_192",
            laser_preset_id: str = "fab_calibration_grid",
            staging_dir: str = "",
            robotics_url: str = "",
            gimp_url: str = "",
            dpi: int = 0,
            push_gimp: bool = False,
        ) -> dict[str, Any]:
            """INKSCAPE_FAB_ART - DXF/laser fab paths, Gazebo schematics, robotics staging.

            Operations: list_presets, batch_dxf_export, batch_laser_dots, gazebo_schematic,
            stage_for_robotics, run_fab_pipeline.
            """
            return await inkscape_fab_art_tool(
                operation=operation,
                input_dir=input_dir,
                output_dir=output_dir,
                svg_path=svg_path,
                png_path=png_path,
                preset_id=preset_id,
                laser_preset_id=laser_preset_id,
                staging_dir=staging_dir,
                robotics_url=robotics_url,
                gimp_url=gimp_url,
                dpi=dpi,
                push_gimp=push_gimp,
                cli_wrapper=self.cli_wrapper,
                config=self.config,
            )

        @self.mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=False,
                openWorldHint=True,
            ),
        )
        async def inkscape_sim_art(
            operation: InkscapeSimArtOperation,
            input_dir: str = "",
            output_dir: str = "",
            output_path: str = "",
            template_id: str = "ui_icon_128",
            layout: str = "2x2",
            cell_size: int = 128,
            margin_px: int = 0,
            bleed_px: int = 0,
            staging_dir: str = "",
            gimp_url: str = "",
            target_platform: str = "unity",
            validate: bool = True,
            goal: str = "",
            dpi: int = 192,
        ) -> dict[str, Any]:
            """INKSCAPE_SIM_ART - UI icon packs, vector sheets, Resonite/VRChat staging.

            Operations: list_presets, svg_pack_batch, build_icon_sheet, audit_svg_pack,
            ai_svg_refine_loop, push_gimp_texture_sheet, stage_resonite_ui, run_sim_pipeline.
            """
            return await inkscape_sim_art_tool(
                operation=operation,
                input_dir=input_dir,
                output_dir=output_dir,
                output_path=output_path,
                template_id=template_id,
                layout=layout,
                cell_size=cell_size,
                margin_px=margin_px,
                bleed_px=bleed_px,
                staging_dir=staging_dir,
                gimp_url=gimp_url,
                target_platform=target_platform,
                validate=validate,
                goal=goal,
                dpi=dpi,
                cli_wrapper=self.cli_wrapper,
                config=self.config,
            )

        @self.mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=True,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
        async def inkscape_system(
            operation: InkscapeSystemOperation,
            action: str = "",
            svg_content: str = "",
            text: str = "Prova MCP OK",
            search: str = "",
            limit: int = 100,
            offset: int = 0,
            input_path: str = "",
            output_path: str = "",
            session_id: str = "desktop",
        ) -> dict[str, Any]:
            """INKSCAPE_SYSTEM - Diagnostics, native actions, and addressed desktop documents.

            PORTMANTEAU RATIONALE: Operational and introspection calls stay in one discoverable tool.

            Operations: status, execution_mode, hands_in_command, help, diagnostics, version,
            config, list_extensions, execute_extension, self_terminate,
            active_document, insert_svg, draw_test, list_actions,
            list_documents, open_document, new_document, install_live_extension,
            save_document, save_copy, close_document.

            Args:
                operation: System subcommand (Literal). Extension execution may require extra
                    parameters not exposed on this MCP wrapper - prefer list_extensions first.
                action: Semicolon-separated Inkscape actions for hands_in_command. Requires
                    a running Inkscape GUI and access to its desktop session.
                svg_content: Complete SVG XML to insert into session_id through the native effect.
                    Requires Linux, gdbus, and install_live_extension; restart existing windows once.
                text: Editable demo label for draw_test. Inserts a blue rectangle and text,
                    preserves existing objects, and verifies live content without using the clipboard.
                search: Case-insensitive name/description substring for list_actions.
                limit: Maximum CLI actions per page for list_actions (1-500, default 100).
                offset: Starting index in filtered list_actions results (default 0).
                input_path: Existing SVG to open in a separate managed session.
                output_path: New SVG path for new_document (refuses overwrite), or snapshot
                    destination for save_copy (preserves the GUI filename).
                session_id: Managed ID returned by list_documents/open_document/new_document,
                    or desktop for an existing single-window instance. Save/close require a managed ID.

            Returns:
                Dict with success, message, data, execution_time_ms, error.

            Errors:
                Missing Inkscape or native extension, unavailable/ambiguous session, or unverified
                edit/save. Inspect the target before retrying an uncertain mutation.
            """
            return await inkscape_system_tool(
                operation=operation,
                action=action,
                svg_content=svg_content,
                text=text,
                search=search,
                limit=limit,
                offset=offset,
                input_path=input_path,
                output_path=output_path,
                session_id=session_id,
                cli_wrapper=self.cli_wrapper,
                config=self.config,
            )

        @self.mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=True,
            ),
        )
        async def list_local_models() -> dict[str, Any]:
            """LIST_LOCAL_MODELS - Discover Ollama and LM Studio model IDs on localhost (read-only).

            Returns:
                Dict with success, operation, summary, result.ollama / result.lm_studio lists,
                and errors[] for unreachable endpoints (bounded).

            Errors:
                Both endpoints down - result still returns with empty lists and diagnostic strings.
            """
            return await list_local_models_tool()

        @self.mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=True,
                idempotentHint=False,
                openWorldHint=True,
            ),
        )
        async def llm_ops(
            operation: Literal["list_models", "loaded", "switch_model", "unload_all", "vram"],
            provider: str = "ollama",
            model: str = "",
            endpoint: str = "",
        ) -> dict[str, Any]:
            """LLM_OPS - Manage the local LLM engine from an agent (same engine
            path the webapp AI Settings page uses - UI and MCP clients cannot drift).

            Ops: list_models (Ollama + LM Studio model IDs) | loaded (Ollama
            residents + VRAM) | switch_model (make `model` the only resident:
            evict rest, warm it) | unload_all (evict everything) | vram
            (per-GPU telemetry). Only Ollama supports loaded/switch/unload -
            it is the only engine with a load/unload API.

            Returns:
                Dict with success, operation, provider, plus op-specific fields
                (evicted/warmed/engine for switch_model/unload_all, models for
                loaded/list_models, gpus for vram).

            Errors:
                switch_model with an empty model - use list_models first, then
                pass a name from that list. Non-ollama + loaded/switch/unload -
                returns success=False with recovery_options instead of pretending.
            """
            return await llm_ops_tool(operation, provider=provider, model=model, endpoint=endpoint)

        self.tools = {
            "inkscape_file": inkscape_file,
            "inkscape_vector": inkscape_vector,
            "inkscape_analysis": inkscape_analysis,
            "inkscape_render": inkscape_render,
            "inkscape_validation": inkscape_validation,
            "inkscape_fleet": inkscape_fleet,
            "inkscape_fab_art": inkscape_fab_art,
            "inkscape_sim_art": inkscape_sim_art,
            "inkscape_system": inkscape_system,
            "list_local_models": list_local_models,
            "llm_ops": llm_ops,
        }


async def main_async():
    """Async entry point."""
    # Configure basic logging first
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        force=True,
        handlers=[logging.StreamHandler(sys.stderr)],
    )
    logger = logging.getLogger(__name__)

    parser = argparse.ArgumentParser(description="Inkscape MCP Server")
    parser.add_argument("--config", type=str, help="Path to config file", default=None)
    parser.add_argument("--mode", choices=["stdio", "http", "dual"], default=None)
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="HTTP port when dual/http transport is used (fleet webapp backend; Vite proxies /mcp and /api here)",
    )
    parser.add_argument("--host", default=None)
    parser.add_argument("--log-level", default="INFO")

    args = parser.parse_args()

    # Re-setup logging with arg level
    log_level = getattr(logging, args.log_level.upper())
    logging.basicConfig(level=log_level, force=True)

    from .utils.structured_logging import configure_json_logging_if_enabled

    configure_json_logging_if_enabled()

    # Only explicit CLI values override the environment. In particular, leaving
    # --mode out must not turn a stdio MCP client into an HTTP listener.
    if args.mode is not None:
        os.environ["MCP_TRANSPORT"] = "stdio" if args.mode == "stdio" else "http"
    else:
        os.environ.setdefault("MCP_TRANSPORT", "stdio")
    if args.port is not None:
        os.environ["MCP_PORT"] = str(args.port)
    else:
        os.environ.setdefault("MCP_PORT", "11027")
    if args.host is not None:
        os.environ["MCP_HOST"] = args.host

    try:
        server = InkscapeMCPServer(config_path=Path(args.config) if args.config else None)
        if await server.initialize():
            # Set module-level app for ASGI compatibility
            import inkscape_mcp

            inkscape_mcp.app = server.mcp
            # Build transport Namespace from already-parsed main.py args
            # instead of stripping sys.argv (which breaks --mode stdio).
            transport_args = argparse.Namespace(
                stdio=args.mode == "stdio",
                http=args.mode in ("http", "dual"),
                sse=False,
                host=args.host,
                port=args.port,
                path=None,
                debug=args.log_level.upper() == "DEBUG",
            )
            await run_server_async(
                server.mcp, args=transport_args, server_name="Inkscape MCP Server"
            )
            logger.info("run_server_async returned (unexpected)")
        else:
            return 1
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception:
        logger.exception("Server error:")
        return 1

    return 0


# Module-level app for ASGI compatibility
app = None  # Will be set when server is initialized


def main():
    """Main entry point."""
    try:
        return asyncio.run(main_async())
    except Exception as e:
        logging.error("Unhandled error in main: %s", e, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
