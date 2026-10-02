FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.13 /uv /uvx /bin/

WORKDIR /app
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock ./
COPY app ./app
RUN uv sync --locked --no-dev

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

