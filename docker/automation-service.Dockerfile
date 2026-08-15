FROM python:3.12.8-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/puzzle-survival

WORKDIR /opt/puzzle-survival

COPY requirements-automation-service.txt /tmp/requirements-automation-service.txt
RUN python -m pip install --no-cache-dir --requirement /tmp/requirements-automation-service.txt \
    && groupadd --system automation \
    && useradd --system --gid automation --home-dir /var/lib/automation-service automation \
    && mkdir -p /var/lib/automation-service/state /var/lib/automation-service/evidence \
    && chown -R automation:automation /var/lib/automation-service

COPY automation_service ./automation_service
COPY safe_action_core ./safe_action_core
COPY tasks ./tasks
COPY scripts ./scripts

USER automation
CMD ["python", "-m", "automation_service", "--mode", "disabled", "--state-path", "/var/lib/automation-service/state/service.sqlite3", "serve"]
