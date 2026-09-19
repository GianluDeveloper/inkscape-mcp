"""Desktop/bundle entry point with stdio and optional HTTP transport.

A sidecar-provided MCP_PORT (or PORT) selects HTTP unless MCP_TRANSPORT or
an explicit --mode selects another transport. Imports also work outside the
bundle's working directory and do not start a server during packaging checks.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

# Frozen builds cannot discover this context implementation via entry points.
os.environ.setdefault("OTEL_PYTHON_CONTEXT", "contextvars_context")

# Keep lazy stdlib extensions visible to PyInstaller's static analysis.
import _datetime  # noqa: F401
import _strptime  # noqa: F401

import cachetools  # noqa: F401
from inkscape_mcp.main import main


def _run() -> int:
    port = os.environ.get("MCP_PORT") or os.environ.get("PORT")
    if port:
        os.environ.setdefault("MCP_PORT", port)
        os.environ.setdefault("MCP_TRANSPORT", "http")
    return main()


if __name__ == "__main__":
    raise SystemExit(_run())
