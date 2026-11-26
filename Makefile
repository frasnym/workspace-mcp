UVICORN := .venv/bin/uvicorn
INSPECTOR := npx @modelcontextprotocol/inspector

.PHONY: help install run inspect smoke

help:
	@echo "install  - install Python dependencies into .venv"
	@echo "run      - serve /mcp on 127.0.0.1:8000 with variables from .env"
	@echo "inspect  - open the Inspector web UI using mcp.json"
	@echo "smoke    - list the server's tools via the Inspector CLI"

install:
	uv sync --frozen

run:
	@test -f .env || { echo "missing .env: cp .env.example .env first" >&2; exit 1; }
	@set -a; . ./.env; set +a; exec $(UVICORN) server:app --host 127.0.0.1 --port 8000 --log-level debug

inspect:
	$(INSPECTOR) --config ./mcp.json

smoke:
	@$(INSPECTOR) --cli --config ./mcp.json --server workspace --method tools/list
