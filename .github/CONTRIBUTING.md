# Contributing

Contributions are welcome for focused bug fixes, documentation updates, and improvements that fit acornwiki's current direction.

## Before You Start

- Check existing issues before opening a new one.
- Discuss large features or architectural changes in an issue before starting implementation.
- Keep changes focused and explain user-facing behavior clearly.
- Do not include personal notes or databases, attachments, exports, credentials, tokens, sensitive logs, unredacted local paths, or generated files.

## Development Setup

From the repository root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt

cd frontend
npm install
cd ..
```

## Local Checks

Run the Python checks from the repository root:

```powershell
pyright
ruff check .
ruff format --check .
```

Run the frontend checks:

```powershell
cd frontend
npm run check
npm run build
cd ..
```

The automated test suite has not been set up yet. When tests are added, run the relevant tests and include the results with your change.

## Issues and Pull Requests

- For bugs, include reproduction steps, expected behavior, actual behavior, and relevant Windows and Python version details.
- Remove personal data, credentials, tokens, and local paths from diagnostics before sharing them.
- Keep pull requests focused and describe what changed, why, and which checks were run.
- Update relevant project documentation when behavior or setup instructions change.
- Do not include unrelated formatting changes, generated builds, or dependency directories.
