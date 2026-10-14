"""Validated, default-off delegated task host configuration."""

from __future__ import annotations

from os import environ

from pydantic import SecretStr

from app.integrations.task_control import SourceTaskSettings

TaskSettings = SourceTaskSettings


def load_task_settings() -> TaskSettings | None:
    enabled = environ.get("FINANCE_TASKS_ENABLED", "false").lower()
    if enabled not in {"true", "false"}:
        raise ValueError("FINANCE_TASKS_ENABLED must be true or false")
    if enabled == "false":
        return None
    return TaskSettings(
        base_url=environ.get("PERSONAL_AI_TASK_BASE_URL", ""),
        audience=environ.get("PERSONAL_AI_TASK_AUDIENCE", ""),
        service_account=environ.get("FINANCE_TASK_SERVICE_ACCOUNT", ""),
        issuer=environ.get("FINANCE_TASK_ISSUER", ""),
        key_id=environ.get("FINANCE_TASK_KEY_ID", ""),
        private_key=SecretStr(environ.get("FINANCE_TASK_PRIVATE_KEY", "")),
        pai_issuer=environ.get("PERSONAL_AI_TASK_ISSUER", ""),
        pai_key_id=environ.get("PERSONAL_AI_TASK_KEY_ID", ""),
        pai_public_key=environ.get("PERSONAL_AI_TASK_PUBLIC_KEY", ""),
        operation_fingerprint=environ.get(
            "FINANCE_TASK_SHOPPING_OPERATION_FINGERPRINT", ""
        ),
    )
