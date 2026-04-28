# Two-stage build: uv builds the venv from the lockfile, runtime
# image is python:3.12-slim with the venv copied in. uvicorn runs
# as PID 1 so SIGTERM reaches Python promptly.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Install deps without touching project source first so this layer
# caches across source-only rebuilds. README.md is referenced by
# pyproject.toml's `readme = ...` so it has to be present even
# during the deps-only sync.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev

# Now bring the source and install the project itself.
COPY src ./src
RUN uv sync --frozen --no-dev


FROM python:3.12-slim AS runtime

# Run as a non-root user.
RUN groupadd --system --gid 1000 talkshow \
 && useradd --system --uid 1000 --gid 1000 \
       --home /app --shell /sbin/nologin talkshow

WORKDIR /app

# Bring the venv + source over from the build stage.
COPY --from=builder --chown=talkshow:talkshow /app /app

# The cache dir is created with permissions the runtime user can
# write to. Operators should bind-mount this so the audio cache
# survives container rebuilds.
RUN mkdir -p /app/cache && chown -R talkshow:talkshow /app/cache

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER talkshow
EXPOSE 8000

CMD ["uvicorn", "talkshow.main:app", "--host", "0.0.0.0", "--port", "8000"]
