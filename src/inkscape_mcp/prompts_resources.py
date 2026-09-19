"""Workflow prompts and capability resources for the public Inkscape MCP API.

Registers MCP prompts (prompt://inkscape/...) and resources (resource://inkscape/...)
so clients that list prompts/resources see real entries, not only MCPB bundle text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_prompts_and_resources(mcp: FastMCP) -> None:
    """Attach prompts and resources to the given FastMCP instance."""

    @mcp.prompt("prompt://inkscape/svg-file-workflow")
    def prompt_svg_file_workflow() -> str:
        """Guide file-level SVG workflows (load, convert, validate)."""
        return """Guide the user through Inkscape MCP file operations.
1. Call inkscape_system(operation="status") and inspect data.inkscape.available, or use operation="version".
2. Use inkscape_file(operation="info", input_path="...") for format and basic metadata.
3. Use inkscape_file(operation="validate", input_path="...") before heavy edits.
4. Use inkscape_file(operation="convert", input_path="...", output_path="...", format="pdf|png|...") for exports.
5. Prefer absolute paths the server is allowed to read; respect allowed_directories in config."""

    @mcp.prompt("prompt://inkscape/vector-editing-workflow")
    def prompt_vector_editing_workflow() -> str:
        """Guide vector edits via inkscape_vector."""
        return """Guide vector editing with inkscape_vector (Inkscape CLI --actions).
1. Start from inkscape_analysis(operation="dimensions", input_path="...") or "statistics" for context.
2. Use tools/list for exact public arguments. Typical flows include path_simplify, path_clean, and apply_boolean with operation_type="union|difference|intersection|exclusion" and object_ids or select_all.
3. Create explicit shapes and editable text with construct_svg(output_path="...", svg_content="<svg xmlns='http://www.w3.org/2000/svg'>...</svg>").
4. For live editing, use inkscape_system operations list_documents, active_document, and insert_svg with the intended session_id. Install the native extension explicitly before the first edit.
5. File edits need input_path and output_path; inspect success and output paths. Live edits require data.verified and do not automatically save the document."""

    @mcp.prompt("prompt://inkscape/analysis-workflow")
    def prompt_analysis_workflow() -> str:
        """Guide document analysis before editing."""
        return """Use inkscape_analysis to understand an SVG before changing it.
1. inkscape_analysis(operation="statistics", input_path="...")
2. inkscape_analysis(operation="objects", input_path="...") for structure
3. inkscape_analysis(operation="validate", input_path="...")
4. inkscape_analysis(operation="dimensions", input_path="...")
5. Summarize findings and propose the smallest set of inkscape_vector / inkscape_file calls to meet the user goal."""

    @mcp.prompt("prompt://inkscape/sampling-agentic-workflow")
    def prompt_sampling_agentic_workflow() -> str:
        """Explain SEP-1577 / ctx.sample agentic tools."""
        return """When the MCP client supports sampling and sampling.tools:
- generate_svg: the client model produces SVG through sampling; FastMCP injects Context, so do not provide ctx in JSON.
- agentic_inkscape_workflow, intelligent_vector_processing, conversational_inkscape_assistant return plans or guidance, not completed editing workflows (see docs/AI_SAMPLING.md).

If sampling is unavailable, use inkscape_vector(operation="construct_svg") and explicit editing calls.
Optional: list_local_models() discovers local providers. Dashboard generation uses its configured model services separately and does not add sampling capability to an MCP client."""

    @mcp.prompt("prompt://inkscape/heraldry-workflow")
    def prompt_heraldry_workflow() -> str:
        """Heraldry-specific generation."""
        return """For heraldic assets use generate_heraldry(operation="trumponia", output_path="...") when registered.
Confirm output path is under an allowed directory. Combine with inkscape_file / inkscape_vector for post-processing if needed."""

    @mcp.resource("resource://inkscape/capabilities")
    def resource_capabilities() -> str:
        """Static capability summary for indexers and clients."""
        return """inkscape-mcp 2.6.0 (FastMCP >=3.4.4,<4)
Tools: inkscape_file, inkscape_vector, inkscape_analysis, inkscape_render, inkscape_validation, inkscape_system, inkscape_fleet, inkscape_fab_art, inkscape_sim_art, list_local_models, llm_ops, generate_heraldry.
Sampling tools (when their module loads): generate_svg, agentic_inkscape_workflow, intelligent_vector_processing, conversational_inkscape_assistant. They require client sampling.tools; planning helpers return plans rather than executing every described edit.
Use tools/list for exact operations and arguments. Installed extensions and internal Python helpers are not automatically registered as MCP tools.
Live Linux desktop: inkscape_system operations install_live_extension, list_documents, new_document, open_document, active_document, insert_svg, draw_test, save_document, save_copy, close_document. Retain session_id to address a managed window. Restart previously open windows after extension installation. Successful edits require data.verified; uncertain edits must not be retried automatically.
Transports: stdio by default; HTTP with MCP_TRANSPORT=http, MCP_PORT default 11027, path /mcp.
HTTP REST dashboard includes /api/health, /api/help, /api/logs, /api/chat, /api/generate-svg. Model-backed features use separately configured providers.
Web UI development explicitly uses backend 11028 and frontend 11029; see web_sota/README.md.
Prompts: prompt://inkscape/svg-file-workflow, vector-editing-workflow, analysis-workflow, sampling-agentic-workflow, heraldry-workflow
Resources: resource://inkscape/capabilities, resource://inkscape/skills"""

    @mcp.resource("resource://inkscape/skills")
    def resource_skills() -> str:
        """LLM-oriented skill reference loaded from skills/SKILL.md (CodeMode discovery)."""
        from pathlib import Path

        skill_path = Path(__file__).parent / "skills" / "SKILL.md"
        if skill_path.exists():
            return skill_path.read_text(encoding="utf-8")
        return "Skills file not found - expected at src/inkscape_mcp/skills/SKILL.md"
