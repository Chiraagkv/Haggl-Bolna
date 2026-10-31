.PHONY: install run live test check tunnel db demo fake

install:
	python -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt

run:
	uvicorn app.main:app --reload --port 8000

# Everything in one go: tunnel, Bolna agents + tool + extractions, server. Ctrl+C stops it all.
live:
	python3 scripts/start.py

test:
	python -m pytest -q

check:
	python scripts/check_setup.py

tunnel:
	bash scripts/tunnel.sh

db:
	docker compose up -d db

demo:
	python scripts/run_demo.py

fake:
	python3 scripts/start.py --fake
