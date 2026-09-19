# Legacy MCPB layout

This directory is retained for `tools/sync_mcpb_src.py` and
`tools/pack_mcpb.py`. The canonical runtime is `src/inkscape_mcp/`; this directory's
`src/` is a generated staging copy and must not be committed. The sync script also
copies the repository's license and attribution files into the bundle.

The manifest describes the current 16 MCP tools and forces stdio. It expects a
Python 3.12+ interpreter with project dependencies already installed, plus the
Inkscape desktop application. The old unused configuration controls were removed;
configure Inkscape through the documented environment/configuration options.

For source installation use [INSTALL.md](../INSTALL.md). For the maintained uv
bundle layout and packaging limitations see [docs/MCPB.md](../docs/MCPB.md).
Registry publication is not configured for this fork.
