# Database

Current database: SQLite

Default path:

```text
./data/build_planner.db
```

Docker path:

```text
/app/data/build_planner.db
```

The path is configured with `DATABASE_PATH`. The app still accepts the older
`BUILD_PLANNER_DB` environment variable as a compatibility fallback.

Backup directory:

```text
./data/backups
```

Docker backup directory:

```text
/app/data/backups
```

The backup directory is configured with `BACKUP_DIR`. In Docker it is under the
same persisted `/app/data` volume as the main database.

## Backups and Restore

Backups are available from the Settings page. The app creates backups with
SQLite's backup API instead of directly copying the live database file.

Backup filenames include the project prefix and timestamp, for example:

```text
ignition_backup_2026-06-28_143000.db
```

Restore uploads are staged first, then validated before the user can confirm
replacement. Validation checks:

- `.db` file extension
- SQLite database header
- SQLite quick integrity check
- expected tables: `project`, `task`, `lookupoption`

Before a confirmed restore replaces the current database, the app automatically
creates a pre-restore safety backup in `BACKUP_DIR`. After restore, migrations
run against the restored database and the user may need to reload open pages.

## Migrations

Project Ignition uses a lightweight migration table during the early SQLite
foundation phase.

Table:

```text
schema_migration
```

Columns:

- id
- applied_at

Migrations run automatically during app startup, before SQLModel creates or
uses tables. Migrations are additive and preserve existing data. For example,
the task archive migration adds `task.is_archived` with a default value instead
of requiring the database to be deleted.

## Current Tables

### project

- id
- name
- description
- target_date
- is_archived
- created_at

### task

- id
- project_id
- title
- phase
- category
- priority
- status
- due_date
- estimate_minutes
- notes
- dependency
- is_archived
- created_at

Archived tasks are hidden from normal task lists, dashboard counts, and the
planner. They remain readable through the archived task view and can be restored.

### lookupoption

- id
- group_name
- name
- sort_order
- is_active
- created_at

Lookup options are disabled instead of hard deleted so older tasks remain
readable.

Current groups:

- task_category
- task_status
- priority
- phase

### appsetting

- key
- value
- updated_at

Current keys:

- theme

### schema_migration

- id
- applied_at

## Future Tables

- user
- app_setting
- inventory_item
- inventory_category
- storage_location
- supplier
- bom
- bom_line
- aircraft
- flight_log
- competition
- document
- attachment
- time_entry
- checklist_item
- task_dependency
