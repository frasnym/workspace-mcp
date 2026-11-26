# workspace-mcp

Standalone MCP server for the four Uno digests. Owned by this repo, deployed by `homelab-01`'s `bin/workspace-mcp-deploy.sh`.

It exposes 15 tools (Gmail, Calendar, Tasks) over Streamable HTTP at `/mcp`, built with the official Python MCP SDK and wrapped around the Google APIs using the refresh token in `secret/workspace-mcp`. Hermes' `default` profile calls it as `mcp_servers.workspace` with a bearer token from the same Vault path; the digest cron jobs call it through `google_mcp_client.py`.

## Layout

- `server.py` — MCP server
- `Dockerfile`, `docker-compose.yml`, `pyproject.toml`, `uv.lock` — container and dependencies
- `tests/` — unit tests that pin the SDK server and tool names
- `.vscode/launch.json` — debug config that launches uvicorn through `uv run`, loads `.env`, and serves `127.0.0.1:8000`
- `Makefile` — shortcuts to run the server, open the Inspector, and smoke-test the tools
- `.service` / `.timer` — the timer calls `/usr/local/bin/workspace-mcp-vault-sync.sh` (installed by `homelab-01`) to write `/srv/apps/workspace-mcp/.env` from `secret/workspace-mcp`

## Vault

`secret/workspace-mcp` holds four keys: `WORKSPACE_MCP_TOKEN`, `GOOGLE_MCP_CLIENT_ID`, `GOOGLE_MCP_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`. The `.env` is box-only and never committed; `.env.example` lists the variable names for local runs.

## Deploy

From `homelab-01`: `sudo box-deploy` installs this repo's files and runs its deployer. A change here reaches the box on the next `box-deploy` run.
