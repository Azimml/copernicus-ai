.PHONY: install index run run-dev migrate

# Workers default to 4 — good fit for a 2-4 vCPU VPS (Hetzner CPX21 etc.).
# Override with `make run WORKERS=8` on bigger hardware.
WORKERS ?= 4
HOST    ?= 0.0.0.0
PORT    ?= 8000

install:
	python3 -m venv .venv
	. .venv/bin/activate && pip install --upgrade pip && pip install -r requirements.txt
	. .venv/bin/activate && python -m playwright install chromium

index:
	. .venv/bin/activate && PYTHONPATH=. python scripts/build_index.py

# Production-style: multi-worker, no auto-reload. Use behind a reverse proxy.
run:
	. .venv/bin/activate && uvicorn app.main:app \
		--host $(HOST) --port $(PORT) \
		--workers $(WORKERS) \
		--proxy-headers --forwarded-allow-ips='*'

# Single-worker dev mode with hot reload.
run-dev:
	. .venv/bin/activate && uvicorn app.main:app --host $(HOST) --port $(PORT) --reload

# Migrate existing JSON state into SQLite (one-shot, idempotent).
migrate:
	. .venv/bin/activate && PYTHONPATH=. python scripts/migrate_json_to_sqlite.py
