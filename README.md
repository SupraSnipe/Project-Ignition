# Project Ignition

Internal codename: **Ignition**

Project Ignition is a self-hosted, local-first Workshop Operating System for makers, builders, engineers, hobbyists, and small manufacturers. Its purpose is to reduce the friction between deciding what to do and actually making progress.

The current app is a planning and execution workspace with projects, tasks, Dashboard v2, the Ignite workspace, daily journal notes, a 4-week planner, configurable settings, SQLite storage, migrations, backup/restore, and Docker support.

## Current Status

Version: `0.6.0-alpha`

Current milestone: **Milestone 1 - Planning & Execution**

Current focus: **Workspace v1 ("Ignite")**

## What Works Today

- Dashboard v2 command center with focus tasks, project progress, upcoming/overdue tasks, quick add, recent activity, and planner snapshot.
- Ignite workspace at `/workspace` for daily work, quick completion, today's notes, progress, and upcoming tasks.
- Journal / notes archive at `/workspace/journal` for viewing and editing previous daily workspace notes.
- Projects and tasks with create, edit, archive/restore behavior.
- 4-week planner generated from active task due dates.
- Database-driven lookup settings for task categories, statuses, priorities, and phases.
- Time and localization settings for time zone, date format, time format, week start, and default planner view.
- Global dark/light theme setting.
- SQLite backup download and restore workflow.
- Lightweight migrations, application configuration, logging, and friendly error pages.

## Run With Docker Compose

```bash
docker compose up -d --build
```

Open:

```text
http://localhost:8088
```

## Run Directly On Windows For Development

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

## Main Pages

- `/` - Dashboard command center
- `/workspace` - Ignite daily workspace
- `/workspace/journal` - Journal / notes archive
- `/planner` - 4-week planner
- `/tasks` - active tasks
- `/tasks/archived` - archived tasks
- `/projects` - active projects
- `/settings` - lookup options, localization, backups

## Persistent Data

SQLite database:

```text
./data/build_planner.db
```

Docker database path:

```text
/app/data/build_planner.db
```

Database backups:

```text
./data/backups
```

Back up the `data` folder regularly once real data is entered.

## Configuration

Configuration can be supplied with environment variables or a simple config file pointed to by `APP_CONFIG_FILE`. See `.env.example` for supported values.

Common settings:

- `APP_NAME`
- `APP_ENV`
- `DATABASE_PATH`
- `BACKUP_DIR`
- `LOG_LEVEL`
- `DEFAULT_THEME`
- `APP_TIME_ZONE`

User-facing time and localization preferences are stored in SQLite and can be changed from Settings. Users do not need to edit environment variables to change those preferences after setup.

## Backups And Restore

Database backups can be downloaded and restored from the Settings page. Docker stores generated backups in `./data/backups` through the existing data volume.

Restore uploads are validated before confirmation, and the app creates a pre-restore safety backup before replacing the current database.

## Development Notes

- Stack: FastAPI, SQLModel, SQLite, Jinja2 templates, plain CSS, Docker Compose.
- Most code currently lives in `app/main.py` by design while early workflows settle.
- Database migrations run automatically at startup before the app creates or uses tables.
- The Ignite workspace is rules-based for now. The Ignition Engine, dependencies, time tracking, and command palette are future roadmap items.

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
