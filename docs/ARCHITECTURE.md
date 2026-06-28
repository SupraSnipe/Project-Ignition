# Architecture

## Design Goals

- Local-first
- Self-hosted
- Modular
- Database-driven
- Mobile-friendly
- Useful without cloud services

## Current Stack

- Python
- FastAPI
- SQLModel
- SQLite
- Jinja2 templates
- Plain CSS
- Docker / Docker Compose

## Current Structure

```text
app/
├── main.py
├── static/style.css
└── templates/
```

Most application code still lives in `app/main.py`. That is intentional for
the current foundation milestone so the project stays easy to inspect while
the first workflows settle.

## Foundation Services

- Configuration is read from environment variables and, optionally, a simple
  config file pointed to by `APP_CONFIG_FILE`.
- Startup runs lightweight SQLite migrations before `SQLModel.metadata.create_all`.
- Logging uses Python logging and writes to stdout for Docker compatibility.
- Error handlers render custom 404 and 500 templates without exposing stack traces.
- Theme support is global and app-wide for now. `DEFAULT_THEME` seeds the first
  theme setting, and the header toggle updates the stored app setting.

## Intended Long-Term Structure

```text
Core
├── Users / Auth
├── Settings
├── Projects
├── Tasks
├── Calendar
└── Search

Modules
├── Inventory
├── Manufacturing
├── RC Fleet
├── Competition
├── Documents
└── Analytics
```
