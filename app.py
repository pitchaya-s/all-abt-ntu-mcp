"""Vercel ASGI entrypoint for the public MCP endpoint."""

from shared.http import create_app


app = create_app()
