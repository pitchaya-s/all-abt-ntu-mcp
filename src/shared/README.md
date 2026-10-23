# Shared runtime

STARS, NTULearn, and LibFacilities use the same credential store in `shared.credentials`. Each service manages its own login session and in-memory cache. See the [main README](../../README.md) for installation and MCP client configuration.

## Hosted public server

The Vercel entrypoint is root `app.py`, configured through `tool.vercel.entrypoint` in `pyproject.toml`. It creates `shared.http`'s ASGI app. `shared.public_server` explicitly registers public tool modules, while `shared.server` adds personal tools for local stdio. The hosted import path does not load keyring access, authenticated sessions, personal handlers, or NTULearn.

The HTTP endpoint is `/mcp`, using stateless Streamable HTTP with JSON responses and a 1 MB request limit. Each request manages its own SDK lifecycle, so it works when the host omits ASGI lifespan events or changes event loops between requests. No server session identifier, sticky routing, database, or credentials are required. GET/DELETE on `/mcp` return 405 because there is no persistent event stream or session to delete. `/` and `/health` return public status information.

`vercel.json` selects Singapore and a 300-second function duration. Import the repository root with framework preset **Other**, keeping build/install overrides unset. No environment variables are needed for the default Vercel domains. The app builds its Host/Origin allowlist from `VERCEL_URL`, `VERCEL_PROJECT_PRODUCTION_URL`, and `VERCEL_BRANCH_URL`. For a custom domain, add its bare hostname to `MCP_ALLOWED_HOSTS` in Vercel, then redeploy. Multiple hostnames can be comma-separated; schemes, paths, ports, and wildcards are rejected. Native MCP clients do not need browser CORS access; cross-origin browser clients are not enabled.

Use a publicly accessible deployment URL. Vercel Deployment Protection can require platform sign-in independently of this app.

`.vercelignore` excludes local secrets, browser artifacts, tests, caches, and build output from uploads. No keyring entry or NTU account should be configured on Vercel. Public source caches and request pacing remain bounded per process; caches may disappear on cold starts and are not a shared rate limit across replicas. Configure platform traffic controls if exposing the endpoint to substantial public traffic.

## HTTP tests

From the repository root:

```sh
uv run python -m unittest tests.hosted.test_http -v
uv run uvicorn app:app --host 127.0.0.1 --port 8000
```

In another terminal, the opt-in smoke makes a few public NTU reads:

```sh
uv run python -m tests.hosted.live_smoke http://127.0.0.1:8000/mcp
```

Replace that URL with the Vercel `/mcp` URL to verify a deployment. This repository preparation does not deploy or connect a Vercel project.

For an offline TypeScript SDK check, install the SDK in a temporary npm prefix as described in the main README. Start the synthetic HTTP server instead of the live app:

```sh
uv run uvicorn tests.hosted.protocol_server:app --host 127.0.0.1 --port 8001
```

Then run:

```sh
uv run node tests/hosted/typescript_smoke.mjs "$NTU_MCP_TEST_SDK" http://127.0.0.1:8001/mcp
```

Deployment references: [Vercel Python entrypoints and configuration](https://vercel.com/docs/functions/runtimes/python) and [MCP HTTP deployment guidance](https://py.sdk.modelcontextprotocol.io/run/deploy/).

## Credential storage

Storage is opt-in. Run `all-abt-ntu auth save` yourself in a local terminal; username and password are visible while typing, and piped input is refused. Running it again replaces the saved account/password. `auth status` reports whether an account is stored, and `auth delete` removes it. With uvx, append these arguments to your existing uvx command; no standalone CLI installation is needed. No credential management commands are exposed as MCP tools.

The keyring entry uses service `all-abt-ntu-mcp`, account `ntu-account`. The username, password, and an opaque revision identifier are stored together as the keyring secret. Neither credential is stored in application files, environment variables, or logs, or returned through MCP. Configuration from older versions is not imported automatically; remove any old credentials from `.env` and client settings yourself. A network username is expanded to a student email address for NTULearn; a full NTU email is used as supplied.

Storage uses Python's [keyring library](https://keyring.readthedocs.io/en/latest/) with an allowlist of native Secret Service/KWallet, macOS Keychain, and Windows Credential Manager backends. Plaintext, custom, null, and non-native backends are rejected. A chained backend is used only through its selected native member, without fallback to other members after failure. Unlock the wallet/keychain through its normal OS interface. Locked or unavailable stores return a sanitized error; public tools remain available.

Each authenticated service rereads the entry before personal reads, including cache hits, and before login. Replacing the entry clears that service's old browser session/cache on its next personal operation. Deleting it or losing keyring access blocks the next operation and clears that process's personal session/cache; an already-running request can finish. Session recovery and MFA behavior are described in the individual service guides.

Academic data returned through MCP is visible to the AI client. Credentials and session cookies are excluded from responses. Python/browser memory is not guaranteed to be zeroized. OS keyring permissions govern access by other local processes; keyring storage does not isolate secrets from an agent that can execute arbitrary code as your user.

## Linux keyring access

Linux requires a running Secret Service or KWallet service. Keyring's direct KWallet backend additionally needs `dbus-python` in the same Python environment; KWallet can also provide a Secret Service interface. Some Linux installations need a keyring provider installed and configured first.

If terminal `auth status` works but the MCP does not, forward `DBUS_SESSION_BUS_ADDRESS` and `XDG_RUNTIME_DIR` through the client's MCP configuration and restart the client from that same terminal. Codex uses `env_vars`, as shown in the main README. Do not hardcode another user's bus address or start a separate D-Bus session for the MCP.

In authentication tool results, `credentials_configured` is `true` when the account is readable, `false` when the keyring is readable but has no account, and `null` when storage cannot be read. A keyring error does not establish that credentials are missing.
