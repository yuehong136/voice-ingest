.PHONY: sync check test integration serve worker
sync:
	uv sync --all-extras --frozen
check:
	uv run ruff check .
	uv run ruff format --check .
	uv run pyright
	uv run pytest -m 'not integration'
test:
	uv run pytest -m 'not integration'
integration:
	uv run pytest -m integration
serve:
	uv run voice-ingest-server
worker:
	uv run voice-ingest-worker
