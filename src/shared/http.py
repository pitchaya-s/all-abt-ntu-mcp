"""Stateless HTTP application exposing only public NTU tools."""

import os
import re

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import public_server


def transport_security():
    hosts = {"localhost", "127.0.0.1", "[::1]"}
    configured = [os.environ.get(name, "") for name in (
        "VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL", "VERCEL_BRANCH_URL",
    )]
    configured.extend(os.environ.get("MCP_ALLOWED_HOSTS", "").split(","))
    for host in configured:
        host = host.strip().lower()
        if not host:
            continue
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host):
            raise ValueError("MCP host configuration must contain hostnames without schemes, paths, or ports.")
        hosts.add(host)
    allowed = sorted(hosts | {host + ":*" for host in hosts})
    origins = {"https://" + host for host in allowed}
    origins.update("http://" + host for host in allowed if host.startswith(("localhost", "127.0.0.1", "[::1]")))
    return TransportSecuritySettings(allowed_hosts=allowed, allowed_origins=sorted(origins))


class PublicMCP:
    def __init__(self, server, security):
        self.server = server
        self.security = security

    async def __call__(self, scope, receive, send):
        # Vercel may omit ASGI lifespan events or use a new event loop for the next request.
        app = self.server.streamable_http_app(
            stateless_http=True, json_response=True, transport_security=self.security,
            max_request_body_size=1_000_000,
        )
        async with app.router.lifespan_context(app):
            await app(scope, receive, send)


async def health(request):
    return JSONResponse({"name": "all-abt-ntu-mcp", "mode": "public", "mcp": "/mcp"})


def create_app():
    server = MCPServer(
        "all-abt-ntu-mcp", version="0.1.0", log_level="WARNING",
        instructions=(
            "This hosted server exposes only public, read-only NTU information. "
            "It does not accept credentials, log in, read personal records, or modify plans. "
            + public_server.INSTRUCTIONS
        ),
    )
    public_server.register_tools(server)
    return Starlette(routes=[
        Route("/", health), Route("/health", health),
        Route("/mcp", PublicMCP(server, transport_security()), methods=["POST"]),
    ])
