# Shared runtime

STARS, NTULearn, LibFacilities, One Stop, and CareerAxis use the same credential store in `shared.credentials`. Each service manages its own login session and in-memory cache. See the [main README](../../README.md) for installation and MCP client configuration and the [One Stop guide](../onestop/README.md) for student ServiceNow tools.

## Hosted public server

The Vercel entrypoint is the file-based function `api/index.py`. `vercel.json` selects the **Other** framework preset and rewrites requests to that function, which creates `shared.http`'s ASGI app. `shared.public_server` explicitly registers public tool modules, while `shared.server` adds personal tools for local stdio. The hosted import path does not load keyring access, authenticated sessions, personal handlers, or NTULearn.

The HTTP endpoint is `/mcp`, using stateless Streamable HTTP with JSON responses and a 1 MB request limit. Each request manages its own SDK lifecycle, so it works when the host omits ASGI lifespan events or changes event loops between requests. No server session identifier, sticky routing, database, or credentials are required. GET/DELETE on `/mcp` return 405 because there is no persistent event stream or session to delete. `/` and `/health` return public status information.

`vercel.json` selects Singapore and a 300-second function duration. Import the repository root with framework preset **Other**, keeping build/install overrides unset. No environment variables are needed for the default Vercel domains. The app builds its Host/Origin allowlist from `VERCEL_URL`, `VERCEL_PROJECT_PRODUCTION_URL`, and `VERCEL_BRANCH_URL`. For a custom domain, add its bare hostname to `MCP_ALLOWED_HOSTS` in Vercel, then redeploy. Multiple hostnames can be comma-separated; schemes, paths, ports, and wildcards are rejected. Native MCP clients do not need browser CORS access; cross-origin browser clients are not enabled.

Use a publicly accessible deployment URL. Vercel Deployment Protection can require platform sign-in independently of this app.

`.vercelignore` excludes local secrets, browser artifacts, tests, caches, and build output from uploads. No keyring entry or NTU account should be configured on Vercel. Public source caches and request pacing remain bounded per process; caches may disappear on cold starts and are not a shared rate limit across replicas. Configure platform traffic controls if exposing the endpoint to substantial public traffic.

## HTTP tests

From the repository root:

```sh
uv run python -m unittest tests.hosted.test_http -v
uv run uvicorn api.index:app --host 127.0.0.1 --port 8000
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

Deployment references: [Vercel file-based Python functions](https://vercel.com/docs/functions/runtimes/python/api-directory) and [MCP HTTP deployment guidance](https://py.sdk.modelcontextprotocol.io/run/deploy/).

## Credential storage

Storage is opt-in. Run `all-abt-ntu auth save` yourself in a local terminal; the username is visible and the password is hidden while typing. Piped input and terminals that cannot hide password input are refused. Credentials are stored encrypted in the native OS keyring and never included in MCP responses sent to the LLM. Running the command again replaces the saved account/password. `auth status` reports whether an account is stored, and `auth delete` removes it. With uvx, append these arguments to your existing uvx command; no standalone CLI installation is needed. No credential management commands are exposed as MCP tools.

The keyring entry uses service `all-abt-ntu-mcp`, account `ntu-account`. The username, password, and an opaque revision identifier are stored together as the keyring secret. Neither credential is stored in application files, environment variables, or logs, or returned through MCP. Configuration from older versions is not imported automatically; remove any old credentials from `.env` and client settings yourself. A network username is expanded to a student email address for NTULearn; a full NTU email is used as supplied.

Storage uses Python's [keyring library](https://keyring.readthedocs.io/en/latest/) with an allowlist of native Secret Service/KWallet, macOS Keychain, and Windows Credential Manager backends. Plaintext, custom, null, and non-native backends are rejected. A chained backend is used only through its selected native member, without fallback to other members after failure. Unlock the wallet/keychain through its normal OS interface. Locked or unavailable stores return a sanitized error; public tools remain available.

Authenticated services check credentials before personal operations and before login. NTULearn checks the keyring once at the start of each data-tool operation, including operations served from cache; its auth-status tool reports storage availability without authenticating. Other services retain their own check timing. Replacing the entry clears an affected service's old session and cache on its next personal operation. Deleting it or losing keyring access prevents the next keyring-based login; an already-running operation can finish. NTULearn may still authenticate with opt-in, validated browser cookies when no keyring credentials are available. Session recovery and MFA behavior are described in the individual service guides.

Academic data returned through MCP is visible to the AI client. Credentials and session cookies are excluded from responses. Python/browser memory is not guaranteed to be zeroized. OS keyring permissions govern access by other local processes; keyring storage does not isolate secrets from an agent that can execute arbitrary code as your user.

## Public HTTP reads

Faculty, news, campus services, OneSearch, MazeMap, and DR-NTU use a pooled HTTP client for public HTTPS reads. Each service keeps a bounded five-minute response cache, reuses connections, limits concurrent requests, and spaces request starts. The client follows only HTTPS redirects to that service's allowlisted hosts, rejects cookies, bounds responses to 8 MB, and makes at most one retry for transient network errors, HTTP 429, or selected 5xx responses. It honors short `Retry-After` delays and returns an error rather than retrying before a longer delay.

Set these variables before starting the server to tune the public-read scheduler:

| Variable | Default | Range | Effect |
| --- | --- | --- | --- |
| `NTU_PUBLIC_HTTP_CONCURRENCY` | `2` | 1–8 | Maximum in-flight requests per host across public service clients in this process |
| `NTU_PUBLIC_HTTP_INTERVAL_SECONDS` | `0.25` | 0–10 | Minimum spacing between request starts to the same host across public service clients in this process |
| `NTU_PUBLIC_HTTP_TIMEOUT_SECONDS` | `20` | 1–120 | Request timeout in seconds |
| `NTU_PUBLIC_HTTP_MAX_RETRY_DELAY_SECONDS` | `10` | 0–30 | Longest provider-requested wait the client will perform before retrying |

These limits are shared by all public clients in this process, grouped by host; hosted replicas keep independent limits. Omnibus and authenticated NTU endpoints use distinct request owners and are not merged into this public client.

## Linux keyring access

Linux requires a running Secret Service or KWallet service. Keyring's direct KWallet backend additionally needs `dbus-python` in the same Python environment; KWallet can also provide a Secret Service interface. Some Linux installations need a keyring provider installed and configured first.

If terminal `auth status` works but the MCP does not, forward `DBUS_SESSION_BUS_ADDRESS` and `XDG_RUNTIME_DIR` through the client's MCP configuration and restart the client from that same terminal. Codex uses `env_vars`, as shown in the main README. Do not hardcode another user's bus address or start a separate D-Bus session for the MCP.

If `busctl --user list` cannot connect, point the current shell at its desktop session bus before checking credentials or launching the MCP client:

```sh
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
busctl --user list
uv run all-abt-ntu auth status
```

The keyring service must appear in the bus listing, and `auth status` must report the account as stored. Restart the MCP client from this corrected session so it inherits the same bus address.

In authentication tool results, `credentials_configured` is `true` when the account is readable, `false` when the keyring is readable but has no account, and `null` when storage cannot be read. A keyring error does not establish that credentials are missing.
