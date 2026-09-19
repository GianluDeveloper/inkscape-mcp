# Building distributions

Release publication is not configured for this fork. Building artifacts locally
or in CI does not publish them to PyPI, the MCP Registry, or GitHub Releases.
No upstream account, namespace, artifact URL, or checksum should be reused.

## Python package

From the repository root with Python 3.12+, uv, Inkscape, and the native libraries
listed in [INSTALL.md](INSTALL.md):

```bash
uv sync --frozen --group dev
uv run --frozen pytest tests
uv build --no-build-isolation
uv run --frozen twine check dist/*
```

The resulting wheel and source archive are in `dist/`. For an installation check,
install the wheel into a separate environment with its dependencies and call the
MCP server from outside the source checkout. Native Inkscape operations and live
desktop editing must be checked separately; a valid package archive alone does
not establish that those external dependencies are available.

## Desktop bundle

See [docs/MCPB.md](docs/MCPB.md). The maintained `mcpb/` layout stages the current
source, dependency metadata, uv lockfile, license and attribution before packing.
The `mcp-server/` directory supports the older Python packer. Neither layout
bundles the Inkscape desktop application or all native operating-system libraries.

Before distributing a bundle, validate its manifest, connect an MCP client to the
unpacked artifact, and exercise native operations on each supported target.
Retain [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).

## Configuring a future release

A maintainer must select and authenticate publication accounts owned by this
fork, establish a versioning/release policy, and test the artifact to be released.
An MCP Registry record must reference the real published artifact and its exact
SHA-256 checksum. Publication should be a deliberate maintainer action after
validation; this repository does not provide an automatic release workflow.
