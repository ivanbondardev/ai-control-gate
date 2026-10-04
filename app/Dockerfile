ARG PYTHON_IMAGE=python:3.13-slim-bookworm
FROM ${PYTHON_IMAGE}

ARG APP_VERSION=0.2.0
LABEL org.opencontainers.image.title="Action Gate" \
      org.opencontainers.image.version="${APP_VERSION}"

ENV APP_VERSION=${APP_VERSION} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
RUN groupadd --gid 10001 actiongate \
    && useradd --uid 10001 --gid actiongate --no-create-home actiongate

# requirements.txt includes requirements-mcp.lock, so both files are needed for the install.
COPY requirements.txt requirements-mcp.lock ./
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt

COPY --chown=10001:10001 action_gate ./action_gate
# One image, several commands: the gate MCP ingress, the three dummy services, their local admin CLI
# and the scenario client all come from this image.
COPY --chown=10001:10001 dummy_mcp ./dummy_mcp
COPY --chown=10001:10001 demo_client ./demo_client
COPY --chown=10001:10001 migrations ./migrations
COPY --chown=10001:10001 policy ./policy
COPY --chown=10001:10001 panel_seed.json ./panel_seed.json
COPY --chown=10001:10001 static ./static
COPY --chown=10001:10001 tests ./tests

USER 10001:10001
EXPOSE 8000

# Migrations are a separate one-shot job (compose service ``migrate``); the API and the MCP ingress
# wait for it and never apply schema themselves, so two processes cannot race the same migration.
# The default command keeps the image usable on its own for a single-process run.
CMD ["python", "-m", "action_gate.http_server"]
