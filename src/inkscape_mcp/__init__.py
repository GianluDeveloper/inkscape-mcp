"""
Inkscape MCP Server - Professional Vector Graphics through Model Context Protocol

FastMCP 3 provides grouped tools for SVG files, Inkscape CLI operations,
and verified live document editing. See docs/TOOLS.md for the public contract.

Author: Sandra Schipal
License: MIT
"""

__version__ = "2.6.0"
__author__ = "Sandra Schipal"
__email__ = "sandra@sandraschi.dev"

from .server import InkscapeMcpServer

# Module-level app for ASGI compatibility
from .tools import PORTMANTEAU_TOOLS
from .tools import inkscape_analysis
from .tools import inkscape_file
from .tools import inkscape_system

app = None

__all__ = [
    "InkscapeMcpServer",
    "app",
    "inkscape_file",
    "inkscape_analysis",
    "inkscape_system",
    "PORTMANTEAU_TOOLS",
]
