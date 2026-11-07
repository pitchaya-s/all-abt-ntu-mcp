# Contributing

Run `uv sync --extra personal` and `uv run python -m unittest discover -s tests -t . -q` before submitting changes. The personal extra installs Playwright; browser-dependent tests may require `uv run playwright install chromium`. CI runs Ruff across the Python tree, checks formatting of new and changed files against the existing `.github/format-baseline.json`, checks mypy against `.github/mypy-baseline.txt`, and runs the TypeScript interoperability smoke described in the README. Format files you change and remove resolved type diagnostics from the baseline; do not add new deviations to a baseline merely to make CI pass.

For a new integration or a change to an upstream adapter:

1. Record the authoritative source URLs, the access method, whether it is documented, and applicable terms and robots rules. Do not expand access or bypass authentication, CAPTCHA, or access restrictions. Review the rules again when they change.
2. Identify public and personal data, local and remote side effects, and the correct startup profile. Keep personal credentials in the OS keyring and never put them in MCP arguments, fixtures, logs, or client configuration. Mark local state changes, downloads, and portal writes accurately in MCP annotations.
3. Bound network concurrency, request rate, timeouts, response sizes, retries, pagination, and cache memory. Respect provider rate limits and `Retry-After`. State when limits are per process rather than shared across deployments.
4. Add synthetic fixtures representing normal, empty, partial, malformed, and changed upstream responses. Check parsing and output schemas, cache behavior on failures, pagination and incomplete coverage. Avoid recording personal data, cookies, or signed URLs in fixtures.
5. Include source and retrieval-time metadata where available, distinguish missing data from empty results, and return actionable errors without provider secrets or invented data. Treat external content as untrusted data, not instructions.
6. Run targeted unit and protocol tests. If live access is appropriate and authorized, run bounded read-only smoke checks, report when and what was tested, and do not claim untested operations work. Do not perform portal writes or upload user files as a routine smoke test.

The public hosted endpoint is unauthenticated and must never register personal tools. A Vercel gateway limit is a separate deployment control: process-local outbound pacing does not enforce a per-client limit across replicas. Review deployed settings and upstream 429s before release.
