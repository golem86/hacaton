FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && groupadd --system app \
    && useradd --system --uid 10001 --gid app app \
    && mkdir -p /data \
    && chown app:app /data

COPY --chown=app:app app ./app
USER app
EXPOSE 8000

# seed without --reset initializes only an empty, dedicated demo volume.
# It refuses to overwrite an existing database on later starts.
CMD ["sh", "-c", "python -m app.seed && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log"]
