"""File-based Vercel ASGI function for the public MCP endpoint."""

from shared.http import create_app


app = create_app()
