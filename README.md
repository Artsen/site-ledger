# Artsen Design Scanner

Artsen Design Scanner is a scoped website page inventory tool. PR 1 implements a static HTML crawler that stores page snapshots, link provenance, parsed head metadata, and compressed HTML blobs.

## Local Setup

Backend:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

Frontend:

```powershell
cd frontend
npm install
npm run dev
```

The API defaults to `http://127.0.0.1:8000`; the Vite app defaults to `http://127.0.0.1:5173`.

## Quality Checks

```powershell
cd backend
pytest
ruff check .
ruff format --check .
mypy app
alembic upgrade head
alembic check
```

```powershell
cd frontend
npm run lint
npm run typecheck
npm run test
npm run build
npm run e2e
```

Runtime databases and captured HTML are written under `data/` and ignored by Git.

