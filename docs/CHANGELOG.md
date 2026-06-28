# Changelog

## 0.4.0-alpha - 2026-06-28

### Added

- Lightweight SQLite migration system with a `schema_migration` table.
- App configuration through environment variables or an `APP_CONFIG_FILE`.
- Basic stdout logging for startup, migrations, create/update/archive events, and errors.
- Friendly 404 and 500 error pages.
- Global light/dark theme support with a header toggle.
- Archived task view and task restore action.
- Settings backup controls for downloading SQLite database backups.
- Restore workflow with upload validation, confirmation, and automatic pre-restore safety backup.

### Changed

- Task delete now archives tasks instead of hard deleting them.
- Archived tasks are hidden from normal task lists, the dashboard, and the planner.
- Active project dropdowns exclude archived projects while edit pages keep archived project links readable.
- Docker defaults now use `DATABASE_PATH` while the app still accepts the older `BUILD_PLANNER_DB` variable.
- Docker defaults now store database backups under the persisted `/app/data/backups` directory.

## 0.3.0-alpha - 2026-06-28

### Added

- Project editing for name, description, target date, and archived status.
- Task editing for project, lookup-driven fields, dates, estimates, dependencies, and notes.

## 0.2.0-alpha - 2026-06-28

### Added

- Settings page.
- Database-driven lookup options.
- Editable task categories.
- Editable task statuses.
- Editable priority levels.
- Editable build phases.
- Initial documentation structure.

### Changed

- Task dropdown values now come from SQLite.

## 0.1.0-alpha - 2026-06-28

### Added

- Initial FastAPI app.
- Dockerfile.
- Docker Compose configuration.
- SQLite database.
- Project tracking.
- Task tracking.
- Dashboard.
- 4-week planner.
- Basic styling.
