.PHONY: install index run

install:
	python3 -m venv .venv
	. .venv/bin/activate && pip install --upgrade pip && pip install -r requirements.txt
	. .venv/bin/activate && python -m playwright install chromium

index:
	. .venv/bin/activate && PYTHONPATH=. python scripts/build_index.py

run:
	. .venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
