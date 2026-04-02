# Prasine Index — developer convenience targets.
# Assumes the virtual environment is active: source .venv/bin/activate

.PHONY: install dev test lint format typecheck eval migrate db-start db-stop clean

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

install:
	pip install -r requirements.txt
	pip install ruff mypy alembic

# ---------------------------------------------------------------------------
# Development server
# ---------------------------------------------------------------------------

dev:
	uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------

test:
	pytest tests/ -v

test-cov:
	pytest tests/ -v --cov=. --cov-report=term-missing --cov-omit=".venv/*,tests/*"

# ---------------------------------------------------------------------------
# Golden dataset eval (requires ANTHROPIC_API_KEY and running database)
# ---------------------------------------------------------------------------

eval:
	python -m eval.golden_dataset

eval-quick:
	python -m eval.golden_dataset --quick

eval-case:
	@echo "Usage: make eval-case CASE=GW-001"
	python -m eval.golden_dataset $(CASE)

# ---------------------------------------------------------------------------
# Code quality
# ---------------------------------------------------------------------------

lint:
	ruff check .

lint-fix:
	ruff check --fix .

format:
	ruff format .

format-check:
	ruff format --check .

typecheck:
	mypy agents/ core/ ingest/ models/ api/ eval/

check: lint format-check typecheck test

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

db-start:
	docker compose up -d db

db-stop:
	docker compose down

db-reset:
	docker compose down -v && docker compose up -d db

db-init:
	python -c "import asyncio; from core.database import init_db; asyncio.run(init_db())"

# Alembic migrations
migrate:
	alembic upgrade head

migration:
	@echo "Usage: make migration MSG='add embedding column'"
	alembic revision --autogenerate -m "$(MSG)"

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

clean:
	find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} +
	find . -type f -name "*.pyc" -not -path "./.venv/*" -delete
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
