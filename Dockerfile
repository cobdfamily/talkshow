# Talkshow container image. Single-stage; the deps fit and pip's
# wheel cache stays inside the layer for fast rebuilds.

FROM python:3.12-slim

# Slim ships without build tools; the azure-cognitiveservices-speech
# wheel is prebuilt for linux/amd64 so no compile step is needed at
# install time. Add gcc here only if you flip on a multi-arch build
# that needs to compile something.

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install deps first so the layer is reusable across source-only
# rebuilds.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App source. .dockerignore keeps secrets, caches, and venvs out
# of the build context.
COPY app /app/app
COPY main.py /app/main.py

# Run as a non-root user. The cache dir is created with permissions
# the runtime user can write to.
RUN groupadd --system --gid 1000 talkshow \
 && useradd --system --uid 1000 --gid 1000 --home /app --shell /sbin/nologin talkshow \
 && mkdir -p /app/cache \
 && chown -R talkshow:talkshow /app

USER talkshow

EXPOSE 8000

# uvicorn directly so signals (SIGTERM) reach Python promptly.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
