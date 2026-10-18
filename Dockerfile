# The API (FastAPI + the agent) as a production image, run as an unprivileged user.
#   docker compose --profile app build api
# The same image runs the one-off jobs: migrations, the data loader and create_admin.py, e.g.
#   docker compose --profile app run --rm api python scripts/migrate.py
# Secrets come from the environment (.env through docker compose), never from the image.

FROM python:3.12.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src:/app
WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

# What the API and the jobs read at run time (see .dockerignore for what is left out).
COPY pyproject.toml ./
COPY src ./src
COPY prompts ./prompts
COPY glossary ./glossary
COPY db ./db
COPY scripts ./scripts
COPY eval ./eval

RUN useradd --uid 10001 --create-home app \
    && mkdir -p /app/eval/cache/llm /app/data/raw \
    && chown -R app:app /app/eval/cache /app/data
USER app

EXPOSE 8000
# --proxy-headers: the client address comes from X-Forwarded-For, set by the web server from
# Caddy's header. Trusted from any sender because the API is reachable only on Docker's
# private network (it publishes no port).
CMD ["uvicorn", "orderintel.api.app:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips=*", "--no-server-header"]
