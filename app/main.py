from __future__ import annotations

import os
import logging
import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
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


class AppSetting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str
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

        connection.commit()
    logger.info("Database migrations complete")


def init_db() -> None:
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        theme_setting = session.get(AppSetting, "theme")
        if not theme_setting:
            session.add(AppSetting(key="theme", value=DEFAULT_THEME))

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


def render(request: Request, template_name: str, context: dict, status_code: int = 200):
    with Session(engine) as session:
        theme = get_current_theme(session)
    base_context = {
        "request": request,
        "app_name": APP_NAME,
        "app_env": APP_ENV,
        "current_theme": theme,
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


@app.get("/")
def dashboard(request: Request):
    with Session(engine) as session:
        projects = get_projects(session)
        tasks = get_active_tasks(session)
        pmap = task_project_map(session)

    active_tasks = [t for t in tasks if t.status != "Complete"]
    complete_tasks = [t for t in tasks if t.status == "Complete"]
    today = date.today()
    overdue = [t for t in active_tasks if t.due_date and t.due_date < today]
    due_week = [t for t in active_tasks if t.due_date and today <= t.due_date <= today + timedelta(days=7)]

    completion = round((len(complete_tasks) / len(tasks)) * 100) if tasks else 0

    return render(
        request,
        "dashboard.html",
        {
            "projects": projects,
            "tasks": tasks,
            "active_tasks": active_tasks,
            "complete_tasks": complete_tasks,
            "overdue": overdue,
            "due_week": sorted(due_week, key=lambda t: t.due_date or date.max),
            "completion": completion,
            "pmap": pmap,
            "estimate_label": estimate_label,
        },
    )


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
        session.add(task)
        session.commit()
        logger.info("Created task id=%s title=%s", task.id, task.title)
    return RedirectResponse("/tasks", status_code=303)


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
        task.status = status
        task.due_date = parse_optional_date(due_date)
        task.estimate_minutes = estimate_minutes
        task.dependency = dependency.strip()
        task.notes = notes.strip()
        session.add(task)
        session.commit()
        logger.info("Updated task id=%s archived=%s", task.id, task.is_archived)
    return RedirectResponse("/tasks", status_code=303)


@app.post("/tasks/{task_id}/status")
def update_task_status(task_id: int, status: str = Form(...)):
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if not task:
            raise HTTPException(status_code=404)
        task.status = status
        session.add(task)
        session.commit()
        logger.info("Updated task status id=%s status=%s", task.id, task.status)
    return RedirectResponse("/tasks", status_code=303)


@app.post("/tasks/{task_id}/delete")
def delete_task(task_id: int):
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if not task:
            raise HTTPException(status_code=404)
        task.is_archived = True
        session.add(task)
        session.commit()
        logger.info("Archived task id=%s title=%s", task.id, task.title)
    return RedirectResponse("/tasks", status_code=303)


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
def planner_page(request: Request, start: str = ""):
    if start:
        start_date = date.fromisoformat(start)
    else:
        today = date.today()
        start_date = today - timedelta(days=(today.weekday() + 1) % 7)

    end_date = start_date + timedelta(days=27)

    with Session(engine) as session:
        tasks = session.exec(
            select(Task)
            .where(Task.is_archived == False)
            .where(Task.due_date >= start_date)
            .where(Task.due_date <= end_date)
            .order_by(Task.due_date, Task.priority, Task.title)
        ).all()
        pmap = task_project_map(session)

    by_day = {start_date + timedelta(days=i): [] for i in range(28)}
    for task in tasks:
        if task.due_date in by_day:
            by_day[task.due_date].append(task)

    weeks = []
    for w in range(4):
        week = []
        for d in range(7):
            day = start_date + timedelta(days=w * 7 + d)
            week.append({"date": day, "tasks": by_day[day]})
        weeks.append(week)

    return render(
        request,
        "planner.html",
        {
            "weeks": weeks,
            "start_date": start_date,
            "end_date": end_date,
            "prev_start": start_date - timedelta(days=28),
            "next_start": start_date + timedelta(days=28),
            "pmap": pmap,
            "estimate_label": estimate_label,
        },
    )


@app.get("/settings")
def settings_page(request: Request):
    with Session(engine) as session:
        lookups = get_all_lookups(session, active_only=False)
    return render(
        request,
        "settings.html",
        {
            "lookups": lookups,
            "lookup_groups": LOOKUP_GROUPS,
            "backup_dir": BACKUP_DIR,
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
