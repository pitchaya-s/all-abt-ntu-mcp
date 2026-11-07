"""Report the installed distribution version to MCP clients."""

from importlib.metadata import PackageNotFoundError, version

try:
    VERSION = version("all-abt-ntu-mcp")
except PackageNotFoundError:
    VERSION = "0+unknown"
