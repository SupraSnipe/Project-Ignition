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
