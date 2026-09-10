FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y libpq-dev && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app
COPY --chown=app:app . .
USER app
EXPOSE 8000
# Migrations deliberately NOT run here: schema changes belong to the
# release step (scripts/migrate.sh, or the compose `migrate` service),
# never to web/worker boot — concurrent replicas would race on locks.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
