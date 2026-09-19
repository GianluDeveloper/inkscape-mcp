# Contributing

Contributions that make Inkscape automation reliable, discoverable, and easier to
reproduce are welcome. Start with [Installation](INSTALL.md) and
[Development](docs/DEVELOPMENT.md).

## Report a problem

Open an [issue](https://github.com/GianluDeveloper/inkscape-mcp/issues) with:

- OS, Python, and Inkscape versions.
- The MCP tool name and exact arguments, with private paths or data removed.
- The returned error and relevant server stderr.
- A minimal SVG or reproduction procedure.
- For desktop problems, X11/Wayland details and whether one Inkscape window was open.

Explain the expected result and the observed result. Please avoid attaching
credentials, private documents, or unrelated logs.

## Make a change

1. Fork or branch from the current `master` branch.
2. Reproduce the behavior before changing it.
3. Make a focused change and add regression tests where behavior warrants them.
4. Run the relevant tests and formatting checks; include results in your PR.
5. Update the public tool schema, dispatch code, and documentation together.

```bash
uv sync --group dev
uv run pytest
uv run ruff check src/inkscape_mcp/path_you_changed.py tests/unit/test_your_change.py
uv run ruff format --check src/inkscape_mcp/path_you_changed.py tests/unit/test_your_change.py
```

The wider repository includes historical scripts and platform-specific tooling.
Report unrelated pre-existing check failures clearly rather than hiding them or
including a broad formatting rewrite in a focused fix.

## Implementation expectations

- Follow the repository's [agent guide](AGENTS.md) and Python 3.12 baseline.
- Group related operations behind a typed `operation` parameter.
- Keep user-visible results structured, with useful failure messages.
- Exercise new parameters through the public MCP schema, not only an internal
  handler. A parameter absent from `tools/list` is not available to an agent.
- Preserve existing files on export failures and reap timed-out/cancelled processes.
- Desktop tests must be explicit about any document mutation. Unit tests should
  use mocked session/clipboard services and never draw into a developer's window.
- Describe which platforms and Inkscape versions you actually tested.

For a PR, describe the concrete problem, resulting behavior, tests, and remaining
limitations. Avoid claims that a platform or integration works without evidence.

## License and attribution

Contributions are provided under the repository's [MIT license](LICENSE).
Preserve existing copyright and license notices when adapting upstream work.
