"""File-based Vercel ASGI function for the public MCP endpoint."""

from public_http_server import create_app


app = create_app()
