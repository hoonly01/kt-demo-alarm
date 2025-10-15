# Repository Guidelines

## Project Structure & Module Organization
- `main.py` — FastAPI entrypoint; mounts routers and config.
- `app/` — modular code:
  - `config/` settings and logging
  - `database/` connection and init helpers
  - `models/` Pydantic DTOs (PascalCase classes)
  - `routers/` API endpoints (async route handlers)
  - `services/` business logic (`*_service.py`)
  - `utils/` shared helpers
- Assets/DB: SQLite file `users.db` (local only), env files `.env`, `.env.example`.

## Build, Test, and Development Commands
- Setup environment:
  - `python3 -m venv venv && source venv/bin/activate`
  - `pip install -r requirements.txt`
  - `cp .env.example .env` and fill Kakao/API keys
- Run locally: `uvicorn main:app --reload --port 8000`
- Quick smoke tests:
  - `curl http://127.0.0.1:8000/` (health)
  - `curl http://127.0.0.1:8000/events/today`
  - `curl -X POST http://127.0.0.1:8000/scheduler/crawl-events`

## Coding Style & Naming Conventions
- Python 3.13+, PEP8, 4-space indent, keep lines ≤ 100 cols.
- Use type hints throughout and Pydantic models for I/O schemas.
- Naming:
  - Files/modules: `snake_case.py`; services end with `_service.py`.
  - Routers live in `app/routers`, grouped by domain (`users.py`, `events.py`).
  - Functions/vars: `snake_case`; classes: `PascalCase`.
- Logging: prefer `app.config.settings.setup_logging()` over prints.

## Testing Guidelines
- No formal suite yet. Use curl-based checks (see above).
- If adding tests, use `pytest` + `httpx.AsyncClient`:
  - Place under `tests/`; name `test_<area>.py`.
  - Aim ≥ 80% coverage for new/changed code.
  - Mock external APIs (Kakao, SMPA) and file I/O.

## Commit & Pull Request Guidelines
- Conventional commits: `feat|fix|chore|docs|style|refactor|test: scope: summary`.
  - Scopes: `routers`, `services`, `models`, `database`, `utils`, `config`.
  - Example: `feat(routers): add /alarms/status endpoint`.
- PRs must include:
  - Clear description, linked issues, BEFORE/AFTER or curl examples.
  - Steps to run locally, any new env vars (update `.env.example`).
  - Screenshots/log snippets for API changes where useful.

## Security & Configuration Tips
- Never commit secrets or `.env`; only update `.env.example`.
- Do not commit local DBs (`users.db`) or large artifacts.
- External calls (Kakao, SMPA) may be rate-limited—mock in tests and guard with retries.
