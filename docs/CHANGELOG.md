# Changelog

## 0.7.0-alpha - Unreleased

### Added

- Planner view modes for Today, This Week, and 4 Weeks.
- Planner Previous, Today, and Next navigation that respects configured time zone and week start.
- Planner Jump to Date control that preserves active filters.
- Planner filters for project, status, priority, category, and archived task inclusion.

### Changed

- Improved planner task cards with project, priority, status, estimate, due date, edit, complete, and archive actions.
- Dashboard and Ignite planner links now open the appropriate planner view.

## 0.6.0-alpha - Unreleased

### Added

- Workspace v1 ("Ignite") page at `/workspace` with focused work cards, workspace summary, upcoming tasks, and progress.
- Navigation link for Ignite and dashboard entry point to the workspace.
- One-note-per-day workspace scratch pad with SQLite persistence and browser autosave.
- Journal / Notes Archive for viewing and editing previous Ignite workspace notes.
- In-place workspace task completion with completion timestamps for progress tracking.

### Changed

- Ignite estimated remaining time now counts only active overdue and due-today tasks; upcoming-week effort is shown separately. Completed Today relies on tasks that have a completion timestamp.

## 0.5.0-alpha - Unreleased

### Added

- Dashboard v2 command-center layout with greeting, date, active work summary, focus list, project progress, upcoming/overdue tasks, quick add, recent activity, and planner snapshot.
- Dashboard quick-add task flow that uses database-driven project and priority options and returns to the dashboard after creation.
- Database-backed time and localization settings for time zone, date format, time format, week start, and default planner view.

### Changed

- Dashboard widgets now exclude archived tasks and archived projects from normal command-center views.

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
