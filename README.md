# acornwiki

`acornwiki` is a planned Windows desktop workspace for organizing personal information as a flexible database, with linked pages and backlinks.

> **Early scaffold:** the application is not yet usable. The repository currently contains a minimal frontend starter; backend behavior, data model, and persistence are not implemented.

## Current Direction

- Frontend: TypeScript, Svelte, and Vite.
- Backend: Python 3.13+ with PyWebView as the frontend bridge.

## Development Setup

From the repository root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt

cd frontend
npm install
npm run dev
```

The Vite development server currently runs the frontend starter by itself; it is not yet connected to the Python application.
