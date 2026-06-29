FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV APP_NAME="Build Planner"
ENV APP_ENV=production
ENV DATABASE_PATH=/app/data/build_planner.db
ENV BACKUP_DIR=/app/data/backups
ENV LOG_LEVEL=INFO
ENV DEFAULT_THEME=light

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
