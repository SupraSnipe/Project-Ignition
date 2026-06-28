from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Field, Session, SQLModel, create_engine, select


DB_PATH = os.getenv("BUILD_PLANNER_DB", "/app/data/build_planner.db")
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})

app = FastAPI(title="Build Planner")
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
    created_at: datetime = Field(default_factory=datetime.utcnow)


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


def init_db() -> None:
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
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
    init_db()


def get_projects(session: Session):
    return session.exec(select(Project).where(Project.is_archived == False).order_by(Project.name)).all()


def get_all_projects(session: Session):
    return session.exec(select(Project).order_by(Project.name)).all()


def task_project_map(session: Session):
    projects = session.exec(select(Project)).all()
    return {p.id: p for p in projects}


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
        tasks = session.exec(select(Task)).all()
        pmap = task_project_map(session)

    active_tasks = [t for t in tasks if t.status != "Complete"]
    complete_tasks = [t for t in tasks if t.status == "Complete"]
    today = date.today()
    overdue = [t for t in active_tasks if t.due_date and t.due_date < today]
    due_week = [t for t in active_tasks if t.due_date and today <= t.due_date <= today + timedelta(days=7)]

    completion = round((len(complete_tasks) / len(tasks)) * 100) if tasks else 0

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
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
    return templates.TemplateResponse("projects.html", {"request": request, "projects": projects})


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
    return RedirectResponse("/projects", status_code=303)


@app.get("/projects/{project_id}/edit")
def edit_project_page(request: Request, project_id: int):
    with Session(engine) as session:
        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404)
    return templates.TemplateResponse("project_edit.html", {"request": request, "project": project})


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
    return RedirectResponse("/projects", status_code=303)


@app.get("/tasks")
def tasks_page(request: Request):
    with Session(engine) as session:
        tasks = session.exec(select(Task).order_by(Task.due_date, Task.priority, Task.title)).all()
        projects = get_projects(session)
        pmap = task_project_map(session)
        lookups = get_all_lookups(session)

    return templates.TemplateResponse(
        "tasks.html",
        {
            "request": request,
            "tasks": tasks,
            "projects": projects,
            "pmap": pmap,
            "lookups": lookups,
            "estimate_label": estimate_label,
        },
    )


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
    return RedirectResponse("/tasks", status_code=303)


@app.get("/tasks/{task_id}/edit")
def edit_task_page(request: Request, task_id: int):
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if not task:
            raise HTTPException(status_code=404)
        projects = get_all_projects(session)
        lookups = get_all_lookups(session, active_only=False)

    return templates.TemplateResponse(
        "task_edit.html",
        {
            "request": request,
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
    return RedirectResponse("/tasks", status_code=303)


@app.post("/tasks/{task_id}/delete")
def delete_task(task_id: int):
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if not task:
            raise HTTPException(status_code=404)
        session.delete(task)
        session.commit()
    return RedirectResponse("/tasks", status_code=303)


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

    return templates.TemplateResponse(
        "planner.html",
        {
            "request": request,
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
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "lookups": lookups,
            "lookup_groups": LOOKUP_GROUPS,
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
    return RedirectResponse("/settings", status_code=303)
