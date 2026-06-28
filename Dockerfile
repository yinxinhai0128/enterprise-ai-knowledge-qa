# Pin both the Python patch release and the multi-platform manifest digest.
FROM python:3.14.6-slim-bookworm@sha256:4ff4b92a68355dbdb52584ab3391dff8d371a61d4e063468bfd0130e3189c6d9

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/home/appuser

WORKDIR /app

RUN groupadd --gid 10001 appuser \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin appuser

# Production installs only the fully resolved, hash-checked runtime graph.
COPY --chown=root:root requirements.lock /app/requirements.lock
RUN python -m pip install --require-hashes --no-deps -r /app/requirements.lock \
    && python -m pip check

# Deliberately copy only runtime source/config. Secrets, tests, Git metadata,
# backups and formal data are excluded from both context and image.
COPY --chown=root:root app /app/app
COPY --chown=root:root config /app/config

# Source remains root-owned and read-only to the runtime identity. Only these
# three persistence mount points are writable by appuser.
RUN mkdir -p /app/storage /app/logs /home/appuser/faiss_kb \
    && chown appuser:appuser /app/storage /app/logs /home/appuser/faiss_kb \
    && chmod 0750 /app/storage /app/logs /home/appuser/faiss_kb \
    && chmod -R a-w /app/app /app/config /app/requirements.lock

USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/ready').status==200 else 1)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
