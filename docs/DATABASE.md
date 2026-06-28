# Database

Current database: SQLite

Default path:

```text
./data/build_planner.db
```

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
- created_at

### lookupoption

- id
- group_name
- name
- sort_order
- is_active
- created_at

Current groups:

- task_category
- task_status
- priority
- phase

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
