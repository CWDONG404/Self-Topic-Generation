# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS runtime

ARG APT_MIRROR_ROOT=
ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN if [ -n "$APT_MIRROR_ROOT" ]; then \
        sed -i \
          -e "s|http://deb.debian.org/debian-security|$APT_MIRROR_ROOT/debian-security|g" \
          -e "s|http://security.debian.org/debian-security|$APT_MIRROR_ROOT/debian-security|g" \
          -e "s|http://deb.debian.org/debian|$APT_MIRROR_ROOT/debian|g" \
          -e "s|https://deb.debian.org/debian-security|$APT_MIRROR_ROOT/debian-security|g" \
          -e "s|https://security.debian.org/debian-security|$APT_MIRROR_ROOT/debian-security|g" \
          -e "s|https://deb.debian.org/debian|$APT_MIRROR_ROOT/debian|g" \
          /etc/apt/sources.list.d/debian.sources; \
    fi \
    && apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=60 update \
    && apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=60 install \
        -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/pip pip install --upgrade pip
RUN --mount=type=cache,target=/root/.cache/pip \
    mkdir app \
    && touch app/__init__.py \
    && pip install ".[documents]" \
    && rm -rf app

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data/storage \
    && chown -R appuser:appuser /app /data
USER appuser

ENV STORAGE_DIR=/data/storage
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
