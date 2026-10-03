FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.13 /uv /uvx /bin/

WORKDIR /app
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock ./
COPY app ./app
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
RUN uv sync --locked --no-dev

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --create-home app \
    && install -d -o 10001 -g 10001 -m 0700 /app/.private

EXPOSE 8000
USER 10001:10001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
