from __future__ import annotations

import os
import logging
import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Field, Session, SQLModel, create_engine, select


def load_config_file(path: str | None) -> dict[str, str]:
    if not path:
        return {}
    config_path = Path(path)
    if not config_path.exists():
        return {}

    values: dict[str, str] = {}
    for line in config_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


CONFIG_FILE = os.getenv("APP_CONFIG_FILE")
FILE_CONFIG = load_config_file(CONFIG_FILE)


def config_value(name: str, default: str) -> str:
    if name == "DATABASE_PATH":
        return os.getenv("DATABASE_PATH") or os.getenv("BUILD_PLANNER_DB") or FILE_CONFIG.get(name, default)
    return os.getenv(name) or FILE_CONFIG.get(name, default)


APP_NAME = config_value("APP_NAME", "Build Planner")
APP_ENV = config_value("APP_ENV", "development")
DB_PATH = config_value("DATABASE_PATH", "/app/data/build_planner.db")
BACKUP_DIR = config_value("BACKUP_DIR", "/app/data/backups")
LOG_LEVEL = config_value("LOG_LEVEL", "INFO").upper()
DEFAULT_THEME = config_value("DEFAULT_THEME", "light").lower()
if DEFAULT_THEME not in {"light", "dark"}:
    DEFAULT_THEME = "light"
DEFAULT_TIME_ZONE = config_value("APP_TIME_ZONE", os.getenv("TZ", "UTC"))
DEFAULT_DATE_FORMAT = "MM/DD/YYYY"
DEFAULT_TIME_FORMAT = "12-hour"
DEFAULT_WEEK_STARTS_ON = "Sunday"
DEFAULT_PLANNER_VIEW = "4 Weeks"

TIME_ZONE_OPTIONS = [
    ("UTC", "UTC"),
    ("America/New_York", "Eastern Time"),
    ("America/Chicago", "Central Time"),
    ("America/Denver", "Mountain Time"),
    ("America/Phoenix", "Arizona Time"),
    ("America/Los_Angeles", "Pacific Time"),
    ("America/Anchorage", "Alaska Time"),
    ("Pacific/Honolulu", "Hawaii Time"),
    ("Europe/London", "London"),
    ("Europe/Berlin", "Central Europe"),
    ("Asia/Tokyo", "Tokyo"),
    ("Australia/Sydney", "Sydney"),
]

DATE_FORMAT_OPTIONS = [
    ("MM/DD/YYYY", "MM/DD/YYYY"),
    ("DD/MM/YYYY", "DD/MM/YYYY"),
    ("YYYY-MM-DD", "YYYY-MM-DD"),
    ("Month D, YYYY", "Month D, YYYY"),
]

TIME_FORMAT_OPTIONS = [
    ("12-hour", "12-hour"),
    ("24-hour", "24-hour"),
]

WEEK_START_OPTIONS = [
    ("Sunday", "Sunday"),
    ("Monday", "Monday"),
]

PLANNER_VIEW_OPTIONS = [
    ("Today", "Today"),
    ("This Week", "This Week"),
    ("4 Weeks", "4 Weeks"),
]


def valid_time_zone_name(value: str) -> bool:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError:
        return False
    return True


if not valid_time_zone_name(DEFAULT_TIME_ZONE):
    DEFAULT_TIME_ZONE = "UTC"

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("project_ignition")

Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
Path(BACKUP_DIR).mkdir(parents=True, exist_ok=True)

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})

app = FastAPI(title=APP_NAME)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


class Project(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    description: str = ""
    target_date: Optional[date] = None
    is_archived: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class LookupOption(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    group_name: str = Field(index=True)
    name: str
    sort_order: int = 100
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Task(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: Optional[int] = Field(default=None, foreign_key="project.id")
    title: str
    phase: str = ""
    category: str = "Assembly"
    priority: str = "Normal"
    status: str = "Not Started"
    due_date: Optional[date] = None
    estimate_minutes: int = 30
    notes: str = ""
    dependency: str = ""
    is_archived: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class AppSetting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class WorkspaceNote(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    note_date: date = Field(index=True, unique=True)
    content: str = ""
    updated_at: datetime = Field(default_factory=datetime.utcnow)


LOOKUP_GROUPS = {
    "task_category": "Task Categories",
    "task_status": "Task Statuses",
    "priority": "Priority Levels",
    "phase": "Build Phases",
}

DEFAULT_LOOKUPS = {
    "task_category": [
        "Design",
        "3D Printing",
        "Laser Cutting",
        "Composite Work",
        "Assembly",
        "Electronics",
        "Testing",
        "Waiting on Parts",
        "Admin",
    ],
    "task_status": [
        "Not Started",
        "In Progress",
        "Blocked",
        "Waiting",
        "Complete",
    ],
    "priority": [
        "Critical",
        "High",
        "Normal",
        "Low",
    ],
    "phase": [
        "Planning",
        "Design",
        "Prototype",
        "Fabrication",
        "Assembly",
        "Finishing",
        "Testing",
        "Logistics",
    ],
}

EXPECTED_RESTORE_TABLES = {"project", "task", "lookupoption"}


def timestamp_slug() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def backup_name_prefix() -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", APP_NAME.lower()).strip("_")
    if slug == "build_planner":
        return "ignition"
    return slug or "ignition"


def backup_filename(kind: str = "backup") -> str:
    prefix = backup_name_prefix()
    if kind == "safety":
        return f"{prefix}_pre_restore_{timestamp_slug()}.db"
    if kind == "pending":
        return f"restore_pending_{timestamp_slug()}.db"
    return f"{prefix}_backup_{timestamp_slug()}.db"


def backup_path(filename: str) -> Path:
    path = (Path(BACKUP_DIR) / filename).resolve()
    backup_root = Path(BACKUP_DIR).resolve()
    if backup_root not in path.parents and path != backup_root:
        raise HTTPException(status_code=400, detail="Invalid backup path")
    return path


def create_database_backup(kind: str = "backup") -> Path:
    destination = backup_path(backup_filename(kind))
    source = sqlite3.connect(DB_PATH)
    try:
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
            target.commit()
        finally:
            target.close()
    finally:
        source.close()
    logger.info("Created %s database backup at %s", kind, destination)
    return destination


def validate_database_backup(path: Path) -> tuple[bool, str]:
    if path.suffix.lower() != ".db":
        return False, "Backup files must use the .db extension."

    try:
        with path.open("rb") as handle:
            header = handle.read(16)
        if header != b"SQLite format 3\x00":
            return False, "Uploaded file is not a SQLite database."

        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            quick_check = connection.execute("PRAGMA quick_check").fetchone()
            if not quick_check or quick_check[0] != "ok":
                return False, "SQLite integrity check failed."
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            tables = {row[0] for row in rows}
        finally:
            connection.close()
    except sqlite3.Error:
        logger.exception("Restore validation failed for %s", path)
        return False, "Uploaded file could not be read as a SQLite database."
    except OSError:
        logger.exception("Restore validation could not read %s", path)
        return False, "Uploaded file could not be read."

    missing = sorted(EXPECTED_RESTORE_TABLES - tables)
    if missing:
        return False, f"Backup is missing expected tables: {', '.join(missing)}."
    return True, ""


def pending_restore_path(filename: str) -> Path:
    if Path(filename).name != filename or not filename.startswith("restore_pending_"):
        raise HTTPException(status_code=400, detail="Invalid restore file")
    return backup_path(filename)


def restore_database_from_backup(path: Path) -> Path:
    valid, message = validate_database_backup(path)
    if not valid:
        logger.warning("Rejected restore from %s: %s", path, message)
        raise HTTPException(status_code=400, detail=message)

    safety_backup = create_database_backup(kind="safety")
    engine.dispose()
    replacement = sqlite3.connect(path)
    try:
        target = sqlite3.connect(DB_PATH)
        try:
            replacement.backup(target)
            target.commit()
        finally:
            target.close()
    finally:
        replacement.close()
    logger.info("Restored database from %s after safety backup %s", path, safety_backup)
    run_migrations()
    init_db()
    return safety_backup


def table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def column_exists(connection: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    return any(row[1] == column_name for row in connection.execute(f"PRAGMA table_info({table_name})"))


def ensure_migration_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migration (
            id TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )


def migration_applied(connection: sqlite3.Connection, migration_id: str) -> bool:
    row = connection.execute("SELECT id FROM schema_migration WHERE id = ?", (migration_id,)).fetchone()
    return row is not None


def record_migration(connection: sqlite3.Connection, migration_id: str) -> None:
    connection.execute(
        "INSERT OR IGNORE INTO schema_migration (id, applied_at) VALUES (?, ?)",
        (migration_id, datetime.utcnow().isoformat()),
    )


def run_migrations() -> None:
    logger.info("Checking database migrations for %s", DB_PATH)
    with sqlite3.connect(DB_PATH) as connection:
        ensure_migration_table(connection)

        if not migration_applied(connection, "0001_add_task_is_archived"):
            if table_exists(connection, "task") and not column_exists(connection, "task", "is_archived"):
                connection.execute("ALTER TABLE task ADD COLUMN is_archived BOOLEAN NOT NULL DEFAULT 0")
                logger.info("Applied migration 0001_add_task_is_archived")
            else:
                logger.info("Recorded migration 0001_add_task_is_archived; no task table change needed")
            record_migration(connection, "0001_add_task_is_archived")

        if not migration_applied(connection, "0002_create_app_settings"):
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS appsetting (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
            logger.info("Applied migration 0002_create_app_settings")
            record_migration(connection, "0002_create_app_settings")

        if not migration_applied(connection, "0003_workspace_notes_and_task_completed_at"):
            if table_exists(connection, "task") and not column_exists(connection, "task", "completed_at"):
                connection.execute("ALTER TABLE task ADD COLUMN completed_at DATETIME")
                logger.info("Applied task completed_at migration")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS workspacenote (
                    id INTEGER PRIMARY KEY,
                    note_date DATE NOT NULL UNIQUE,
                    content TEXT NOT NULL DEFAULT '',
                    updated_at DATETIME NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS ix_workspacenote_note_date ON workspacenote (note_date)"
            )
            logger.info("Applied migration 0003_workspace_notes_and_task_completed_at")
            record_migration(connection, "0003_workspace_notes_and_task_completed_at")

        connection.commit()
    logger.info("Database migrations complete")


def init_db() -> None:
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        theme_setting = session.get(AppSetting, "theme")
        if not theme_setting:
            session.add(AppSetting(key="theme", value=DEFAULT_THEME))
        time_zone_setting = session.get(AppSetting, "time_zone")
        if not time_zone_setting:
            session.add(AppSetting(key="time_zone", value=DEFAULT_TIME_ZONE))
        localization_defaults = {
            "date_format": DEFAULT_DATE_FORMAT,
            "time_format": DEFAULT_TIME_FORMAT,
            "week_starts_on": DEFAULT_WEEK_STARTS_ON,
            "default_planner_view": DEFAULT_PLANNER_VIEW,
        }
        for key, value in localization_defaults.items():
            if not session.get(AppSetting, key):
                session.add(AppSetting(key=key, value=value))

        for group_name, names in DEFAULT_LOOKUPS.items():
            existing = session.exec(select(LookupOption).where(LookupOption.group_name == group_name)).first()
            if not existing:
                for index, name in enumerate(names, start=1):
                    session.add(LookupOption(group_name=group_name, name=name, sort_order=index * 10))
        session.commit()

        existing_project = session.exec(select(Project)).first()
        if existing_project:
            return

        projects = [
            Project(name="TigRES T4", description="RC sailplane build and kit development."),
            Project(name="F5J Altimeter", description="AMRT/altimeter prototype project."),
            Project(name="DNRC Part", description="Composite mold and replacement part work."),
            Project(name="Nationals Prep", description="Practice, logistics, and event prep."),
        ]
        session.add_all(projects)
        session.commit()
        for project in projects:
            session.refresh(project)

        today = date.today()
        sample_tasks = [
            Task(project_id=projects[0].id, title="Review wing build sequence", phase="Planning", category="Design", priority="High", due_date=today, estimate_minutes=30),
            Task(project_id=projects[0].id, title="Print servo tray test piece", phase="Prototype", category="3D Printing", priority="Normal", due_date=today + timedelta(days=1), estimate_minutes=45),
            Task(project_id=projects[1].id, title="Check BOM against PCBWay quote", phase="Fabrication", category="Electronics", priority="Critical", due_date=today + timedelta(days=2), estimate_minutes=30),
            Task(project_id=projects[2].id, title="Prep mold flange material", phase="Fabrication", category="Composite Work", priority="High", due_date=today + timedelta(days=3), estimate_minutes=60),
            Task(project_id=projects[3].id, title="Pack field charging setup", phase="Logistics", category="Admin", priority="Normal", due_date=today + timedelta(days=4), estimate_minutes=30),
        ]
        session.add_all(sample_tasks)
        session.commit()


@app.on_event("startup")
def on_startup() -> None:
    logger.info("Starting %s in %s mode", APP_NAME, APP_ENV)
    run_migrations()
    init_db()
    logger.info("Startup complete")


def get_current_theme(session: Session) -> str:
    setting = session.get(AppSetting, "theme")
    if setting and setting.value in {"light", "dark"}:
        return setting.value
    return DEFAULT_THEME


def get_current_time_zone(session: Session) -> str:
    setting = session.get(AppSetting, "time_zone")
    if setting and valid_time_zone_name(setting.value):
        return setting.value
    return DEFAULT_TIME_ZONE


def setting_value(session: Session, key: str, default: str, allowed: set[str] | None = None) -> str:
    setting = session.get(AppSetting, key)
    if setting and (allowed is None or setting.value in allowed):
        return setting.value
    return default


def get_localization_settings(session: Session) -> dict[str, str]:
    return {
        "time_zone": get_current_time_zone(session),
        "date_format": setting_value(
            session,
            "date_format",
            DEFAULT_DATE_FORMAT,
            {value for value, _ in DATE_FORMAT_OPTIONS},
        ),
        "time_format": setting_value(
            session,
            "time_format",
            DEFAULT_TIME_FORMAT,
            {value for value, _ in TIME_FORMAT_OPTIONS},
        ),
        "week_starts_on": setting_value(
            session,
            "week_starts_on",
            DEFAULT_WEEK_STARTS_ON,
            {value for value, _ in WEEK_START_OPTIONS},
        ),
        "default_planner_view": setting_value(
            session,
            "default_planner_view",
            DEFAULT_PLANNER_VIEW,
            {value for value, _ in PLANNER_VIEW_OPTIONS},
        ),
    }


def current_app_datetime(session: Session) -> datetime:
    return datetime.now(ZoneInfo(get_current_time_zone(session)))


def format_date_for_setting(value: date, date_format: str) -> str:
    if date_format == "DD/MM/YYYY":
        return value.strftime("%d/%m/%Y")
    if date_format == "YYYY-MM-DD":
        return value.isoformat()
    if date_format == "Month D, YYYY":
        return value.strftime("%B %d, %Y")
    return value.strftime("%m/%d/%Y")


def format_time_for_setting(value: datetime, time_format: str) -> str:
    if time_format == "24-hour":
        return value.strftime("%H:%M")
    return value.strftime("%I:%M %p").lstrip("0")


def render(request: Request, template_name: str, context: dict, status_code: int = 200):
    with Session(engine) as session:
        theme = get_current_theme(session)
        localization_settings = get_localization_settings(session)
    base_context = {
        "request": request,
        "app_name": APP_NAME,
        "app_env": APP_ENV,
        "current_theme": theme,
        "current_time_zone": localization_settings["time_zone"],
        "localization_settings": localization_settings,
    }
    base_context.update(context)
    return templates.TemplateResponse(template_name, base_context, status_code=status_code)


def get_projects(session: Session):
    return session.exec(select(Project).where(Project.is_archived == False).order_by(Project.name)).all()


def get_all_projects(session: Session):
    return session.exec(select(Project).order_by(Project.name)).all()


def task_project_map(session: Session):
    projects = session.exec(select(Project)).all()
    return {p.id: p for p in projects}


def get_active_tasks(session: Session):
    return session.exec(select(Task).where(Task.is_archived == False)).all()


def get_lookup_options(session: Session, group_name: str, active_only: bool = True):
    query = select(LookupOption).where(LookupOption.group_name == group_name)
    if active_only:
        query = query.where(LookupOption.is_active == True)
    return session.exec(query.order_by(LookupOption.sort_order, LookupOption.name)).all()


def get_all_lookups(session: Session, active_only: bool = True):
    return {key: get_lookup_options(session, key, active_only=active_only) for key in LOOKUP_GROUPS}


def parse_optional_date(value: str | None) -> Optional[date]:
    if not value:
        return None
    return date.fromisoformat(value)


def estimate_label(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h" if mins == 0 else f"{hours}h {mins}m"


def priority_rank(priority: str) -> int:
    return {"Critical": 0, "High": 1, "Normal": 2, "Low": 3}.get(priority, 4)


def first_lookup_name(lookups: dict[str, list[LookupOption]], group_name: str, fallback: str) -> str:
    options = lookups.get(group_name, [])
    return options[0].name if options else fallback


def due_status_label(task: Task, today: date) -> str:
    if not task.due_date:
        return "No Due Date"
    if task.due_date < today:
        return "Overdue"
    if task.due_date == today:
        return "Today"
    if task.due_date <= today + timedelta(days=7):
        return "Due Soon"
    return task.due_date.strftime("%b %d")


def default_planner_view_slug(localization_settings: dict[str, str]) -> str:
    return {
        "Today": "today",
        "This Week": "week",
        "4 Weeks": "4weeks",
    }.get(localization_settings.get("default_planner_view", DEFAULT_PLANNER_VIEW), "4weeks")


def normalize_planner_view(view: str, localization_settings: dict[str, str]) -> str:
    if view in {"today", "week", "4weeks"}:
        return view
    return default_planner_view_slug(localization_settings)


def week_start_for(day: date, week_starts_on: str) -> date:
    if week_starts_on == "Monday":
        return day - timedelta(days=day.weekday())
    return day - timedelta(days=(day.weekday() + 1) % 7)


def planner_url(view: str, start: date | None, filters: dict[str, str | bool]) -> str:
    params: dict[str, str] = {"view": view}
    if start:
        params["start"] = start.isoformat()
    for key in ("project_id", "status", "priority", "category"):
        value = filters.get(key)
        if value:
            params[key] = str(value)
    if filters.get("include_archived"):
        params["include_archived"] = "1"
    return f"/planner?{urlencode(params)}"


def task_matches_planner_filters(task: Task, filters: dict[str, str | bool]) -> bool:
    if not filters.get("include_archived") and task.is_archived:
        return False
    if filters.get("project_id") and str(task.project_id or "") != filters["project_id"]:
        return False
    for field_name in ("status", "priority", "category"):
        value = filters.get(field_name)
        if value and getattr(task, field_name) != value:
            return False
    if not filters.get("status") and task.status == "Complete":
        return False
    return True


def greeting_for_hour(hour: int) -> str:
    if 5 <= hour < 12:
        return "Good Morning"
    if hour < 17:
        return "Good Afternoon"
    return "Good Evening"


def active_task_filter(tasks: list[Task], pmap: dict[int, Project]) -> list[Task]:
    return [
        task
        for task in tasks
        if task.status != "Complete"
        and not (task.project_id and pmap.get(task.project_id) and pmap[task.project_id].is_archived)
    ]


def completed_task_filter(tasks: list[Task], pmap: dict[int, Project]) -> list[Task]:
    return [
        task
        for task in tasks
        if task.status == "Complete"
        and not (task.project_id and pmap.get(task.project_id) and pmap[task.project_id].is_archived)
    ]


def workspace_focus_tasks(active_tasks: list[Task], today: date) -> list[Task]:
    # Future hook: replace this rules-based list with Ignition Engine recommendations.
    # TODO: include task dependencies when dependency modeling is promoted.
    # TODO: include time tracking and work-session state when those modules exist.
    week_end = today + timedelta(days=7)
    candidates = [
        task
        for task in active_tasks
        if (task.due_date and task.due_date <= week_end) or task.priority in {"Critical", "High"}
    ]
    return sorted(
        candidates,
        key=lambda task: (
            0 if task.due_date and task.due_date < today else 1,
            0 if task.due_date == today else 1,
            priority_rank(task.priority),
            task.due_date or date.max,
            task.title.lower(),
        ),
    )


def get_workspace_note(session: Session, note_date: date) -> WorkspaceNote:
    note = session.exec(select(WorkspaceNote).where(WorkspaceNote.note_date == note_date)).first()
    return note or WorkspaceNote(note_date=note_date)


@app.get("/")
def dashboard(request: Request):
    with Session(engine) as session:
        projects = get_projects(session)
        tasks = get_active_tasks(session)
        pmap = task_project_map(session)
        lookups = get_all_lookups(session)
        localization_settings = get_localization_settings(session)
        now = current_app_datetime(session)

    active_tasks = active_task_filter(tasks, pmap)
    complete_tasks = completed_task_filter(tasks, pmap)
    today = now.date()
    tomorrow = today + timedelta(days=1)
    week_end = today + timedelta(days=7)
    greeting = greeting_for_hour(now.hour)

    due_today = [t for t in active_tasks if t.due_date == today]
    due_tomorrow = [t for t in active_tasks if t.due_date == tomorrow]
    overdue = [t for t in active_tasks if t.due_date and t.due_date < today]
    due_week = [t for t in active_tasks if t.due_date and today <= t.due_date <= week_end]
    upcoming = [t for t in active_tasks if t.due_date and today <= t.due_date <= week_end]
    high_priority = [t for t in active_tasks if t.priority in {"Critical", "High"} and t not in overdue]

    focus_tasks = overdue + due_today
    if not due_today:
        focus_tasks += [t for t in high_priority if t not in focus_tasks]
    focus_tasks = sorted(
        focus_tasks,
        key=lambda t: (
            0 if t.due_date and t.due_date < today else 1,
            t.due_date or date.max,
            priority_rank(t.priority),
            t.title.lower(),
        ),
    )[:8]

    upcoming_overdue = sorted(
        overdue + upcoming,
        key=lambda t: (
            0 if t.due_date and t.due_date < today else 1,
            t.due_date or date.max,
            priority_rank(t.priority),
            t.title.lower(),
        ),
    )[:12]

    project_cards = []
    for project in projects:
        project_tasks = [t for t in tasks if t.project_id == project.id]
        total_tasks = len(project_tasks)
        completed_count = len([t for t in project_tasks if t.status == "Complete"])
        progress = round((completed_count / total_tasks) * 100) if total_tasks else 0
        project_cards.append(
            {
                "project": project,
                "total_tasks": total_tasks,
                "completed_count": completed_count,
                "progress": progress,
            }
        )

    recent_created = sorted(tasks, key=lambda t: t.created_at, reverse=True)[:5]
    recent_completed = sorted(complete_tasks, key=lambda t: t.created_at, reverse=True)[:5]
    today_estimate_minutes = sum(t.estimate_minutes for t in due_today)

    completion = round((len(complete_tasks) / len(tasks)) * 100) if tasks else 0

    return render(
        request,
        "dashboard.html",
        {
            "greeting": greeting,
            "current_date_label": format_date_for_setting(now.date(), localization_settings["date_format"]),
            "projects": projects,
            "project_cards": project_cards,
            "tasks": tasks,
            "active_tasks": active_tasks,
            "complete_tasks": complete_tasks,
            "due_today": due_today,
            "due_tomorrow": due_tomorrow,
            "overdue": overdue,
            "due_week": sorted(due_week, key=lambda t: t.due_date or date.max),
            "upcoming_overdue": upcoming_overdue,
            "focus_tasks": focus_tasks,
            "recent_created": recent_created,
            "recent_completed": recent_completed,
            "planner_counts": {
                "today": len(due_today),
                "tomorrow": len(due_tomorrow),
                "week": len(due_week),
            },
            "today_estimate_minutes": today_estimate_minutes,
            "completion": completion,
            "pmap": pmap,
            "lookups": lookups,
            "quick_add_defaults": {
                "category": first_lookup_name(lookups, "task_category", "Assembly"),
                "phase": first_lookup_name(lookups, "phase", "Planning"),
            },
            "estimate_label": estimate_label,
            "due_status_label": lambda task: due_status_label(task, today),
        },
    )


@app.get("/workspace")
def workspace_page(request: Request):
    with Session(engine) as session:
        tasks = get_active_tasks(session)
        pmap = task_project_map(session)
        localization_settings = get_localization_settings(session)
        now = current_app_datetime(session)
        today = now.date()
        note = get_workspace_note(session, today)

    active_tasks = active_task_filter(tasks, pmap)
    complete_tasks = completed_task_filter(tasks, pmap)
    focus_tasks = workspace_focus_tasks(active_tasks, today)
    overdue = [task for task in active_tasks if task.due_date and task.due_date < today]
    due_today = [task for task in active_tasks if task.due_date == today]
    today_workload_tasks = sorted(
        overdue + due_today,
        key=lambda task: (
            0 if task.due_date and task.due_date < today else 1,
            task.due_date or date.max,
            priority_rank(task.priority),
            task.title.lower(),
        ),
    )
    completed_today = [
        task
        for task in complete_tasks
        if task.completed_at and task.completed_at.date() == today
    ]
    progress_total = len(today_workload_tasks) + len(completed_today)
    progress_percent = round((len(completed_today) / progress_total) * 100) if progress_total else 0
    estimated_remaining_minutes = sum(task.estimate_minutes for task in today_workload_tasks)
    tomorrow = today + timedelta(days=1)
    week_end = today + timedelta(days=7)
    tomorrow_tasks = sorted(
        [task for task in active_tasks if task.due_date == tomorrow],
        key=lambda task: (priority_rank(task.priority), task.title.lower()),
    )
    next_week_tasks = sorted(
        [task for task in active_tasks if task.due_date and tomorrow < task.due_date <= week_end],
        key=lambda task: (task.due_date or date.max, priority_rank(task.priority), task.title.lower()),
    )
    upcoming_estimate_minutes = sum(task.estimate_minutes for task in tomorrow_tasks + next_week_tasks)

    return render(
        request,
        "workspace.html",
        {
            "title": "Ignite",
            "greeting": greeting_for_hour(now.hour),
            "current_date_label": format_date_for_setting(today, localization_settings["date_format"]),
            "today": today,
            "focus_tasks": focus_tasks,
            "today_workload_tasks": today_workload_tasks,
            "completed_today": completed_today,
            "overdue": overdue,
            "summary": {
                "active_tasks": len(active_tasks),
                "completed_today": len(completed_today),
                "overdue": len(overdue),
                "estimated_remaining_minutes": estimated_remaining_minutes,
                "completion_percent": progress_percent,
                "progress_total": progress_total,
            },
            "tomorrow_tasks": tomorrow_tasks,
            "next_week_tasks": next_week_tasks[:10],
            "upcoming_estimate_minutes": upcoming_estimate_minutes,
            "note": note,
            "pmap": pmap,
            "estimate_label": estimate_label,
            "due_status_label": lambda task: due_status_label(task, today),
            "format_task_date": lambda value: format_date_for_setting(value, localization_settings["date_format"]) if value else "No due date",
        },
    )


@app.post("/workspace/tasks/{task_id}/complete")
def complete_workspace_task(task_id: int, request: Request, next_url: str = Form("/workspace")):
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if not task or task.is_archived:
            raise HTTPException(status_code=404)
        task.status = "Complete"
        task.completed_at = current_app_datetime(session).replace(tzinfo=None)
        session.add(task)
        session.commit()
        logger.info("Completed task from workspace id=%s title=%s", task.id, task.title)

    if request.headers.get("x-requested-with") == "fetch":
        return JSONResponse({"ok": True, "task_id": task_id})
    return RedirectResponse(next_url if next_url.startswith("/") else "/workspace", status_code=303)


@app.post("/workspace/notes")
def update_workspace_note(content: str = Form("")):
    with Session(engine) as session:
        today = current_app_datetime(session).date()
        note = session.exec(select(WorkspaceNote).where(WorkspaceNote.note_date == today)).first()
        if not note:
            note = WorkspaceNote(note_date=today)
        note.content = content
        note.updated_at = datetime.utcnow()
        session.add(note)
        session.commit()
    return JSONResponse({"ok": True})


@app.get("/workspace/journal")
def workspace_journal_page(request: Request):
    with Session(engine) as session:
        localization_settings = get_localization_settings(session)
        notes = session.exec(select(WorkspaceNote).order_by(WorkspaceNote.note_date.desc())).all()

    return render(
        request,
        "journal.html",
        {
            "title": "Journal",
            "notes": notes,
            "format_note_date": lambda value: format_date_for_setting(value, localization_settings["date_format"]),
            "format_note_time": lambda value: format_time_for_setting(value, localization_settings["time_format"]),
        },
    )


@app.get("/workspace/journal/{note_date}")
def workspace_journal_detail_page(request: Request, note_date: str):
    try:
        selected_date = date.fromisoformat(note_date)
    except ValueError:
        raise HTTPException(status_code=404)

    with Session(engine) as session:
        localization_settings = get_localization_settings(session)
        note = get_workspace_note(session, selected_date)

    return render(
        request,
        "journal_detail.html",
        {
            "title": "Journal Note",
            "note": note,
            "note_date": selected_date,
            "note_date_label": format_date_for_setting(selected_date, localization_settings["date_format"]),
        },
    )


@app.post("/workspace/journal/{note_date}")
def update_workspace_journal_note(note_date: str, content: str = Form("")):
    try:
        selected_date = date.fromisoformat(note_date)
    except ValueError:
        raise HTTPException(status_code=404)

    with Session(engine) as session:
        note = session.exec(select(WorkspaceNote).where(WorkspaceNote.note_date == selected_date)).first()
        if not note:
            note = WorkspaceNote(note_date=selected_date)
        note.content = content
        note.updated_at = datetime.utcnow()
        session.add(note)
        session.commit()
    return RedirectResponse(f"/workspace/journal/{selected_date.isoformat()}", status_code=303)


@app.get("/projects")
def projects_page(request: Request):
    with Session(engine) as session:
        projects = get_projects(session)
    return render(request, "projects.html", {"projects": projects})


@app.post("/projects")
def create_project(
    name: str = Form(...),
    description: str = Form(""),
    target_date: str = Form(""),
):
    with Session(engine) as session:
        project = Project(
            name=name.strip(),
            description=description.strip(),
            target_date=parse_optional_date(target_date),
        )
        session.add(project)
        session.commit()
        logger.info("Created project id=%s name=%s", project.id, project.name)
    return RedirectResponse("/projects", status_code=303)


@app.get("/projects/{project_id}/edit")
def edit_project_page(request: Request, project_id: int):
    with Session(engine) as session:
        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404)
    return render(request, "project_edit.html", {"project": project})


@app.post("/projects/{project_id}/edit")
def update_project(
    project_id: int,
    name: str = Form(...),
    description: str = Form(""),
    target_date: str = Form(""),
    is_archived: str = Form("off"),
):
    with Session(engine) as session:
        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404)
        project.name = name.strip()
        project.description = description.strip()
        project.target_date = parse_optional_date(target_date)
        project.is_archived = is_archived == "on"
        session.add(project)
        session.commit()
        logger.info("Updated project id=%s archived=%s", project.id, project.is_archived)
    return RedirectResponse("/projects", status_code=303)


@app.post("/projects/{project_id}/archive")
def archive_project(project_id: int):
    with Session(engine) as session:
        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404)
        project.is_archived = True
        session.add(project)
        session.commit()
        logger.info("Archived project id=%s name=%s", project.id, project.name)
    return RedirectResponse("/projects", status_code=303)


@app.get("/tasks")
def tasks_page(request: Request, archived: str = "0"):
    show_archived = archived in {"1", "true", "yes"}
    with Session(engine) as session:
        tasks = session.exec(
            select(Task)
            .where(Task.is_archived == show_archived)
            .order_by(Task.due_date, Task.priority, Task.title)
        ).all()
        projects = get_projects(session)
        pmap = task_project_map(session)
        lookups = get_all_lookups(session)

    return render(
        request,
        "tasks.html",
        {
            "tasks": tasks,
            "projects": projects,
            "pmap": pmap,
            "lookups": lookups,
            "estimate_label": estimate_label,
            "show_archived": show_archived,
        },
    )


@app.get("/tasks/archived")
def archived_tasks_page(request: Request):
    return tasks_page(request, archived="1")


@app.post("/tasks")
def create_task(
    title: str = Form(...),
    project_id: str = Form(""),
    phase: str = Form(""),
    category: str = Form("Assembly"),
    priority: str = Form("Normal"),
    status: str = Form("Not Started"),
    due_date: str = Form(""),
    estimate_minutes: int = Form(30),
    dependency: str = Form(""),
    notes: str = Form(""),
    next_url: str = Form("/tasks"),
):
    with Session(engine) as session:
        task = Task(
            title=title.strip(),
            project_id=int(project_id) if project_id else None,
            phase=phase,
            category=category,
            priority=priority,
            status=status,
            due_date=parse_optional_date(due_date),
            estimate_minutes=estimate_minutes,
            dependency=dependency.strip(),
            notes=notes.strip(),
        )
        if task.status == "Complete":
            task.completed_at = current_app_datetime(session).replace(tzinfo=None)
        session.add(task)
        session.commit()
        logger.info("Created task id=%s title=%s", task.id, task.title)
    return RedirectResponse(next_url if next_url.startswith("/") else "/tasks", status_code=303)


@app.get("/tasks/{task_id}/edit")
def edit_task_page(request: Request, task_id: int):
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if not task:
            raise HTTPException(status_code=404)
        projects = get_all_projects(session)
        lookups = get_all_lookups(session, active_only=False)

    return render(
        request,
        "task_edit.html",
        {
            "task": task,
            "projects": projects,
            "lookups": lookups,
        },
    )


@app.post("/tasks/{task_id}/edit")
def update_task(
    task_id: int,
    title: str = Form(...),
    project_id: str = Form(""),
    phase: str = Form(""),
    category: str = Form("Assembly"),
    priority: str = Form("Normal"),
    status: str = Form("Not Started"),
    due_date: str = Form(""),
    estimate_minutes: int = Form(30),
    dependency: str = Form(""),
    notes: str = Form(""),
):
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if not task:
            raise HTTPException(status_code=404)
        task.title = title.strip()
        task.project_id = int(project_id) if project_id else None
        task.phase = phase
        task.category = category
        task.priority = priority
        previous_status = task.status
        task.status = status
        if task.status == "Complete" and previous_status != "Complete" and not task.completed_at:
            task.completed_at = current_app_datetime(session).replace(tzinfo=None)
        if task.status != "Complete":
            task.completed_at = None
        task.due_date = parse_optional_date(due_date)
        task.estimate_minutes = estimate_minutes
        task.dependency = dependency.strip()
        task.notes = notes.strip()
        session.add(task)
        session.commit()
        logger.info("Updated task id=%s archived=%s", task.id, task.is_archived)
    return RedirectResponse("/tasks", status_code=303)


@app.post("/tasks/{task_id}/status")
def update_task_status(task_id: int, status: str = Form(...), next_url: str = Form("/tasks")):
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if not task:
            raise HTTPException(status_code=404)
        task.status = status
        if status == "Complete" and not task.completed_at:
            task.completed_at = current_app_datetime(session).replace(tzinfo=None)
        if status != "Complete":
            task.completed_at = None
        session.add(task)
        session.commit()
        logger.info("Updated task status id=%s status=%s", task.id, task.status)
    return RedirectResponse(next_url if next_url.startswith("/") else "/tasks", status_code=303)


@app.post("/tasks/{task_id}/delete")
def delete_task(task_id: int, next_url: str = Form("/tasks")):
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if not task:
            raise HTTPException(status_code=404)
        task.is_archived = True
        session.add(task)
        session.commit()
        logger.info("Archived task id=%s title=%s", task.id, task.title)
    return RedirectResponse(next_url if next_url.startswith("/") else "/tasks", status_code=303)


@app.post("/tasks/{task_id}/restore")
def restore_task(task_id: int):
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if not task:
            raise HTTPException(status_code=404)
        task.is_archived = False
        session.add(task)
        session.commit()
        logger.info("Restored task id=%s title=%s", task.id, task.title)
    return RedirectResponse("/tasks/archived", status_code=303)


@app.get("/planner")
def planner_page(
    request: Request,
    view: str = "",
    start: str = "",
    project_id: str = "",
    status: str = "",
    priority: str = "",
    category: str = "",
    include_archived: str = "0",
):
    with Session(engine) as session:
        localization_settings = get_localization_settings(session)
        today = current_app_datetime(session).date()
        projects = get_projects(session)
        lookups = get_all_lookups(session)
        pmap = task_project_map(session)

        selected_view = normalize_planner_view(view, localization_settings)
        week_starts_on = localization_settings["week_starts_on"]
        filters = {
            "project_id": project_id,
            "status": status,
            "priority": priority,
            "category": category,
            "include_archived": include_archived in {"1", "true", "yes", "on"},
        }

        if start:
            start_date = date.fromisoformat(start)
        elif selected_view == "today":
            start_date = today
        else:
            start_date = week_start_for(today, week_starts_on)

        if selected_view == "today":
            end_date = start_date
            prev_start = start_date - timedelta(days=1)
            next_start = start_date + timedelta(days=1)
            current_start = today
        elif selected_view == "week":
            start_date = week_start_for(start_date, week_starts_on)
            end_date = start_date + timedelta(days=6)
            prev_start = start_date - timedelta(days=7)
            next_start = start_date + timedelta(days=7)
            current_start = week_start_for(today, week_starts_on)
        else:
            selected_view = "4weeks"
            start_date = week_start_for(start_date, week_starts_on)
            end_date = start_date + timedelta(days=27)
            prev_start = start_date - timedelta(days=28)
            next_start = start_date + timedelta(days=28)
            current_start = week_start_for(today, week_starts_on)

        tasks = session.exec(select(Task).order_by(Task.due_date, Task.priority, Task.title)).all()

    filtered_tasks = [task for task in tasks if task_matches_planner_filters(task, filters)]
    dated_tasks = [task for task in filtered_tasks if task.due_date]
    range_tasks = [task for task in dated_tasks if start_date <= task.due_date <= end_date]
    overdue_tasks = sorted(
        [task for task in filtered_tasks if task.due_date and task.due_date < start_date and task.status != "Complete"],
        key=lambda task: (task.due_date or date.max, priority_rank(task.priority), task.title.lower()),
    )
    completed_today = [
        task
        for task in filtered_tasks
        if task.status == "Complete" and task.completed_at and task.completed_at.date() == today
    ]

    day_count = (end_date - start_date).days + 1
    by_day = {start_date + timedelta(days=i): [] for i in range(day_count)}
    for task in range_tasks:
        if task.due_date in by_day:
            by_day[task.due_date].append(task)

    weeks = []
    if selected_view == "4weeks":
        for w in range(4):
            week = []
            for d in range(7):
                day = start_date + timedelta(days=w * 7 + d)
                week.append({"date": day, "tasks": by_day.get(day, [])})
            weeks.append(week)

    week_days = []
    if selected_view == "week":
        week_days = [{"date": start_date + timedelta(days=i), "tasks": by_day[start_date + timedelta(days=i)]} for i in range(7)]

    today_tasks = by_day.get(start_date, []) if selected_view == "today" else []
    today_remaining_tasks = [
        task
        for task in overdue_tasks + today_tasks
        if task.status != "Complete"
    ]
    today_estimate_minutes = sum(task.estimate_minutes for task in today_remaining_tasks)
    week_estimate_minutes = sum(
        task.estimate_minutes for task in range_tasks if task.status != "Complete"
    )

    navigation = {
        "previous": planner_url(selected_view, prev_start, filters),
        "today": planner_url(selected_view, current_start, filters),
        "next": planner_url(selected_view, next_start, filters),
    }
    view_urls = {
        "today": planner_url("today", today, filters),
        "week": planner_url("week", week_start_for(today, week_starts_on), filters),
        "4weeks": planner_url("4weeks", week_start_for(today, week_starts_on), filters),
    }

    return render(
        request,
        "planner.html",
        {
            "title": "Planner",
            "view": selected_view,
            "view_label": {"today": "Today", "week": "This Week", "4weeks": "4 Weeks"}[selected_view],
            "start_date": start_date,
            "end_date": end_date,
            "today": today,
            "navigation": navigation,
            "view_urls": view_urls,
            "filters": filters,
            "projects": projects,
            "lookups": lookups,
            "weeks": weeks,
            "week_days": week_days,
            "today_tasks": today_tasks,
            "overdue_tasks": overdue_tasks,
            "completed_today": completed_today,
            "today_estimate_minutes": today_estimate_minutes,
            "week_estimate_minutes": week_estimate_minutes,
            "pmap": pmap,
            "estimate_label": estimate_label,
            "format_task_date": lambda value: format_date_for_setting(value, localization_settings["date_format"]) if value else "No due date",
            "format_range": lambda first, last: f"{format_date_for_setting(first, localization_settings['date_format'])} - {format_date_for_setting(last, localization_settings['date_format'])}",
            "current_planner_url": str(request.url.path) + (f"?{request.url.query}" if request.url.query else ""),
        },
    )


@app.get("/settings")
def settings_page(request: Request):
    with Session(engine) as session:
        lookups = get_all_lookups(session, active_only=False)
        localization_settings = get_localization_settings(session)
    return render(
        request,
        "settings.html",
        {
            "lookups": lookups,
            "lookup_groups": LOOKUP_GROUPS,
            "backup_dir": BACKUP_DIR,
            "localization": localization_settings,
            "time_zone_options": TIME_ZONE_OPTIONS,
            "date_format_options": DATE_FORMAT_OPTIONS,
            "time_format_options": TIME_FORMAT_OPTIONS,
            "week_start_options": WEEK_START_OPTIONS,
            "planner_view_options": PLANNER_VIEW_OPTIONS,
        },
    )


@app.get("/backups/download")
def download_backup():
    try:
        path = create_database_backup()
    except Exception:
        logger.exception("Backup download failed")
        raise
    logger.info("Serving database backup download %s", path.name)
    return FileResponse(path, media_type="application/octet-stream", filename=path.name)


@app.post("/backups/restore/preview")
def preview_restore(request: Request, backup_file: UploadFile = File(...)):
    original_name = backup_file.filename or ""
    if not original_name.lower().endswith(".db"):
        backup_file.file.close()
        logger.warning("Rejected restore upload with invalid extension: %s", original_name)
        return render(
            request,
            "backup_result.html",
            {
                "title": "Restore Rejected",
                "heading": "Restore Rejected",
                "message": "Backup files must use the .db extension.",
                "success": False,
            },
            status_code=400,
        )

    pending = backup_path(backup_filename("pending"))
    try:
        with pending.open("wb") as destination:
            while chunk := backup_file.file.read(1024 * 1024):
                destination.write(chunk)

        valid, message = validate_database_backup(pending)
        if not valid:
            pending.unlink(missing_ok=True)
            logger.warning("Rejected restore upload %s: %s", original_name, message)
            return render(
                request,
                "backup_result.html",
                {
                    "title": "Restore Rejected",
                    "heading": "Restore Rejected",
                    "message": message,
                    "success": False,
                },
                status_code=400,
            )
    except Exception:
        pending.unlink(missing_ok=True)
        logger.exception("Restore preview failed for %s", original_name)
        return render(
            request,
            "backup_result.html",
            {
                "title": "Restore Error",
                "heading": "Restore Error",
                "message": "The uploaded backup could not be prepared for restore.",
                "success": False,
            },
            status_code=500,
        )
    finally:
        backup_file.file.close()

    logger.info("Staged restore upload %s as %s", original_name, pending.name)
    return render(
        request,
        "backup_confirm.html",
        {
            "title": "Confirm Restore",
            "pending_file": pending.name,
            "original_name": original_name,
        },
    )


@app.post("/backups/restore/confirm")
def confirm_restore(
    request: Request,
    pending_file: str = Form(...),
    confirm_restore: str = Form("off"),
):
    if confirm_restore != "on":
        logger.warning("Restore confirmation missing for %s", pending_file)
        return render(
            request,
            "backup_result.html",
            {
                "title": "Restore Not Confirmed",
                "heading": "Restore Not Confirmed",
                "message": "Check the confirmation box before restoring a backup.",
                "success": False,
            },
            status_code=400,
        )

    try:
        path = pending_restore_path(pending_file)
    except HTTPException as exc:
        logger.warning("Restore rejected for invalid pending file %s: %s", pending_file, exc.detail)
        return render(
            request,
            "backup_result.html",
            {
                "title": "Restore Rejected",
                "heading": "Restore Rejected",
                "message": str(exc.detail),
                "success": False,
            },
            status_code=exc.status_code,
        )

    if not path.exists():
        return render(
            request,
            "backup_result.html",
            {
                "title": "Restore File Missing",
                "heading": "Restore File Missing",
                "message": "The staged restore file could not be found. Upload it again and retry.",
                "success": False,
            },
            status_code=400,
        )

    try:
        safety_backup = restore_database_from_backup(path)
        path.unlink(missing_ok=True)
    except HTTPException as exc:
        logger.warning("Restore rejected for %s: %s", path, exc.detail)
        return render(
            request,
            "backup_result.html",
            {
                "title": "Restore Rejected",
                "heading": "Restore Rejected",
                "message": str(exc.detail),
                "success": False,
            },
            status_code=exc.status_code,
        )
    except Exception:
        logger.exception("Restore failed for %s", path)
        return render(
            request,
            "backup_result.html",
            {
                "title": "Restore Error",
                "heading": "Restore Error",
                "message": "Restore failed. The existing database was not intentionally replaced.",
                "success": False,
            },
            status_code=500,
        )

    return render(
        request,
        "backup_result.html",
        {
            "title": "Restore Complete",
            "heading": "Restore Complete",
            "message": f"Database restored. A pre-restore safety backup was saved as {safety_backup.name}. Reload the app if any page still shows old data.",
            "success": True,
        },
    )


@app.post("/settings/lookups")
def create_lookup_option(
    group_name: str = Form(...),
    name: str = Form(...),
    sort_order: int = Form(100),
):
    if group_name not in LOOKUP_GROUPS:
        raise HTTPException(status_code=400, detail="Invalid lookup group")

    with Session(engine) as session:
        option = LookupOption(
            group_name=group_name,
            name=name.strip(),
            sort_order=sort_order,
            is_active=True,
        )
        session.add(option)
        session.commit()
        logger.info("Created lookup option id=%s group=%s name=%s", option.id, option.group_name, option.name)

    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/lookups/{option_id}")
def update_lookup_option(
    option_id: int,
    name: str = Form(...),
    sort_order: int = Form(100),
    is_active: str = Form("off"),
):
    with Session(engine) as session:
        option = session.get(LookupOption, option_id)
        if not option:
            raise HTTPException(status_code=404)
        option.name = name.strip()
        option.sort_order = sort_order
        option.is_active = is_active == "on"
        session.add(option)
        session.commit()
        logger.info("Updated lookup option id=%s active=%s", option.id, option.is_active)

    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/localization")
def update_localization(
    time_zone: str = Form(...),
    date_format: str = Form(...),
    time_format: str = Form(...),
    week_starts_on: str = Form(...),
    default_planner_view: str = Form(...),
):
    if not valid_time_zone_name(time_zone):
        raise HTTPException(status_code=400, detail="Invalid time zone")
    selected = {
        "time_zone": time_zone,
        "date_format": date_format,
        "time_format": time_format,
        "week_starts_on": week_starts_on,
        "default_planner_view": default_planner_view,
    }
    allowed_values = {
        "date_format": {value for value, _ in DATE_FORMAT_OPTIONS},
        "time_format": {value for value, _ in TIME_FORMAT_OPTIONS},
        "week_starts_on": {value for value, _ in WEEK_START_OPTIONS},
        "default_planner_view": {value for value, _ in PLANNER_VIEW_OPTIONS},
    }
    for key, allowed in allowed_values.items():
        if selected[key] not in allowed:
            raise HTTPException(status_code=400, detail=f"Invalid {key.replace('_', ' ')}")

    with Session(engine) as session:
        for key, value in selected.items():
            setting = session.get(AppSetting, key) or AppSetting(key=key, value=value)
            setting.value = value
            setting.updated_at = datetime.utcnow()
            session.add(setting)
        session.commit()
    logger.info("Updated localization settings time_zone=%s", time_zone)
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/lookups/{option_id}/delete")
def delete_lookup_option(option_id: int):
    with Session(engine) as session:
        option = session.get(LookupOption, option_id)
        if not option:
            raise HTTPException(status_code=404)
        # Safer than a hard delete: disable the option so old tasks remain readable.
        option.is_active = False
        session.add(option)
        session.commit()
        logger.info("Disabled lookup option id=%s group=%s name=%s", option.id, option.group_name, option.name)
    return RedirectResponse("/settings", status_code=303)


@app.post("/theme")
def update_theme(theme: str = Form(...), next_url: str = Form("/")):
    selected_theme = theme if theme in {"light", "dark"} else DEFAULT_THEME
    with Session(engine) as session:
        setting = session.get(AppSetting, "theme") or AppSetting(key="theme", value=selected_theme)
        setting.value = selected_theme
        setting.updated_at = datetime.utcnow()
        session.add(setting)
        session.commit()
    logger.info("Updated global theme to %s", selected_theme)
    return RedirectResponse(next_url if next_url.startswith("/") else "/", status_code=303)


@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    logger.warning("404 Not Found: %s", request.url.path)
    return render(request, "404.html", {"title": "Not Found"}, status_code=404)


@app.exception_handler(Exception)
async def server_error_handler(request: Request, exc: Exception):
    logger.error("Unhandled error on %s", request.url.path, exc_info=(type(exc), exc, exc.__traceback__))
    return render(request, "500.html", {"title": "Server Error"}, status_code=500)
