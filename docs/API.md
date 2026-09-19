# API reference

See [TOOLS.md](TOOLS.md) for the current registered MCP tools and parameters,
[USAGE.md](USAGE.md) for complete requests, and
[CONFIGURATION.md](CONFIGURATION.md) for transport setup.

The running MCP server's `tools/list` response is the authoritative JSON schema.
The optional dashboard's REST routes are implemented in
[app.py](../src/inkscape_mcp/app.py); they are a separate interface from MCP tools.
