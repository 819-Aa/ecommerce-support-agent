FROM ghcr.io/astral-sh/uv:0.11.26-python3.12-trixie-slim

WORKDIR /app

ENV UV_PROJECT_ENVIRONMENT="/usr/local/" \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --only-group client \
    && rm -rf /root/.cache/uv

COPY src/client/ ./client/
COPY src/schema/ ./schema/
COPY src/voice/ ./voice/
COPY src/streamlit_app.py ./
COPY src/mysql_browser.py ./

EXPOSE 8501

CMD ["streamlit", "run", "streamlit_app.py", "--server.address=0.0.0.0"]
