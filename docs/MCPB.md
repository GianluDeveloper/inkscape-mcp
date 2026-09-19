# MCPB packaging

Source installation in [INSTALL.md](../INSTALL.md) is the canonical setup for
this revision. MCPB packaging sources are retained for maintainers; a successful
source checkout does not establish that a published bundle contains the same code.

## Publication status

MCP Registry publication is not configured for this fork. CI builds Python
distributions and the dashboard for validation; it does not publish packages or
create GitHub releases. The inherited `server.json` referenced another
repository's release asset and checksum, so it and the automatic registry
publication workflow were removed.

Before configuring publication, build and test an actual bundle from this
repository, choose a registry namespace owned by its maintainer, and generate
metadata containing that artifact's real release URL and SHA-256. Do not reuse
upstream release metadata. Original authorship is preserved in the Python
metadata, [LICENSE](../LICENSE), and [NOTICE.md](../NOTICE.md).

## Source layouts

- `src/inkscape_mcp/` is the canonical Python package.
- `mcpb/` contains a manifest, bootstrap, dependency metadata, and PowerShell packer.
- `mcp-server/` is the older packaging layout used by the Python packaging scripts.
- `mcpb/src/` and `mcp-server/src/` are generated copies. Do not edit or commit them.

## Current PowerShell workflow

The `mcpb/pack.ps1` script requires PowerShell 7, Bun, uv, and a prepared Windows
virtual environment. It stages the canonical package, validates the bundle,
packs it, unpacks it for a startup check, and removes the staging copy.
The stage also receives the root `pyproject.toml`, `uv.lock`, `LICENSE`, and
`NOTICE.md`; its uv launcher installs locked runtime dependencies with
`--frozen --no-dev` and explicitly selects stdio.

```powershell
uv sync --group dev
pwsh -File mcpb/pack.ps1
```

Read the script's output for the artifact location. Its startup check establishes
that staged imports/startup work in the existing development environment; it does
not prove dependency completeness on a clean consumer machine or a successful
MCP handshake.

The alternative below stages the `mcp-server/` layout and requires Node.js/npm:

```bash
uv run python tools/pack_mcpb.py
```

This produces `dist/inkscape-mcp-v2.6.0.mcpb` and includes the native extension
and attribution files. Its Python launcher expects the runtime dependencies to
be installed already. It is a developer bundle, not the Ubuntu source
installation path or a self-contained Inkscape installer.

## Release checklist

Before distributing a bundle, verify its manifest and dependency declarations
against the current source, perform a real MCP connection using the unpacked
bundle, and test native Inkscape operations. Inkscape and any desktop extension
installation remain external application dependencies. Preserve upstream license
and attribution files for adapted components.
