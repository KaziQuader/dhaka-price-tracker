# Collector image: Python 3.12, uv, Playwright Chromium, Postgres 16 client tools.
FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.12.13 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    # venv outside /app so volume mounts under /app never hide it
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

# Debian bookworm ships pg_dump 15, which refuses to dump a Postgres 16 server, so the client
# comes from the PostgreSQL apt repo (PGDG). libgomp1 is the OpenMP runtime LightGBM needs.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl libgomp1 \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
      https://www.postgresql.org/media/keys/ACCC4CF8.asc \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client-16 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# The browser comes before the Python dependencies, so adding a dependency (which changes
# uv.lock) doesn't reinstall Chromium. It only reinstalls when this version changes.
# Keep it equal to playwright's version in uv.lock; the check below fails the build otherwise.
ARG PLAYWRIGHT_VERSION=1.65.2
# Playwright's bundled Node.js needs libatomic1, which the slim image lacks; --with-deps
# can't add it because Node must start before it installs anything.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libatomic1 \
 && rm -rf /var/lib/apt/lists/* \
 && uvx --no-cache --from "playwright==${PLAYWRIGHT_VERSION}" playwright install --with-deps chromium

# Dependencies next (cached until pyproject.toml or uv.lock change).
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
RUN test "$(python -c 'import importlib.metadata as m; print(m.version("playwright"))')" \
      = "${PLAYWRIGHT_VERSION}" \
 || { echo "PLAYWRIGHT_VERSION in Dockerfile does not match uv.lock" >&2; exit 1; }

# Project code last, so code edits rebuild only this layer.
COPY alembic.ini ./
COPY migrations ./migrations
COPY src ./src
RUN uv sync --locked --no-dev
