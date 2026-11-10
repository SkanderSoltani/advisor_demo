.PHONY: demo demo-local api web web-mock test test-web e2e lint

demo:            ## backend + Dash (Docker Compose if available, else local)
	scripts/demo.sh

demo-local:      ## backend + Dash, always local (uv)
	scripts/demo.sh --local

api:             ## backend only, :8000
	uv run uvicorn app.main:app --reload --port 8000

web:             ## Dash only, :8050, against the backend on :8000
	cd frontend && USE_MOCKS=false uv run python app.py

web-mock:        ## Dash only, :8050, in-process mock backend (no backend needed)
	cd frontend && USE_MOCKS=true uv run python app.py

test:            ## backend tests
	uv run pytest -q

test-web:        ## front-end unit tests (mock backend)
	cd frontend && uv run pytest -q tests/test_mock_backend.py

e2e:             ## Playwright demo flow through the UI (needs `make demo` running)
	cd frontend && uv run pytest -q tests/e2e

lint:
	uv run ruff check . && cd frontend && uv run ruff check .
