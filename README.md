# Project Ignition

Internal codename: **Ignition**

Project Ignition is a self-hosted, local-first workshop/project management application for makers, builders, engineers, and hobbyists.

The first working module is a build planner with projects, tasks, editable settings, a dashboard, a 4-week planner view, SQLite storage, and Docker support.

## Current Status

Version: `0.4.0-alpha`

## Run locally with Docker Compose

```bash
docker compose up -d --build
```

Open:

```text
http://localhost:8088
```

## Run directly on Windows for development

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open:

```text
http://localhost:8000
```

## Persistent data

SQLite database:

```text
./data/build_planner.db
```

Back up the `data` folder regularly once real data is entered.

Configuration can be supplied with environment variables or a simple config
file pointed to by `APP_CONFIG_FILE`. See `.env.example` for supported values.
Database migrations run automatically at startup before the app creates or uses
tables.

Database backups can be downloaded and restored from the Settings page. Docker
stores generated backups in `./data/backups` through the existing data volume.

## Documentation

- `docs/ROADMAP.md`
- `docs/CHANGELOG.md`
- `docs/ARCHITECTURE.md`
- `docs/DATABASE.md`
- `docs/PROJECT_PHILOSOPHY.md`
- `docs/UI_IDEAS.md`
- `docs/FUTURE_FEATURES.md`

## License

Not selected yet.
