# Inkscape MCP bundle sources

This directory contains the maintained MCPB manifest and launcher. The canonical
Python code and dependencies are in the repository root. Source installation is
documented in [INSTALL.md](../INSTALL.md).

`pack.ps1` stages the current source, dependency metadata, uv lockfile and
attribution files before packaging. The launcher uses uv and Python 3.12+;
Inkscape and the native libraries described in the installation guide are
external prerequisites. Live GUI editing additionally requires Linux with a
session bus and the explicitly installed Inkscape extension.

The manifest lists the 16 public MCP tools. Related actions use each tool's
`operation` parameter; REST endpoint names are not MCP tools. Use the server's
`tools/list` response for the current schema.

See [MCPB packaging](../docs/MCPB.md) for validation limits and publication status.
No registry publication or released bundle is configured for this fork.
