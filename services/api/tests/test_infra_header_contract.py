"""Keep API and browser headers reachable through the Firebase API rewrite."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from sqlalchemy import create_engine

from app.main import create_app

ROOT = Path(__file__).resolve().parents[3]


def _api_headers() -> set[str]:
    engine = create_engine("sqlite://")
    app = create_app(engine=engine)
    schema = app.openapi()
    headers = {
        str(parameter["name"]).casefold()
        for path in schema["paths"].values()
        for operation in path.values()
        if isinstance(operation, dict)
        for parameter in operation.get("parameters", [])
        if parameter.get("in") == "header"
    }
    for path in (ROOT / "services/api/app").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "headers"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                headers.add(node.args[0].value.casefold())
    engine.dispose()
    return headers


def test_firebase_routes_preserved_api_headers_and_paths() -> None:
    terraform = (ROOT / "infra/terraform/main.tf").read_text()
    assert 'source = "/api/**"' in terraform
    assert "pinTag = true" in terraform
    from fastapi.testclient import TestClient

    client = TestClient(create_app(engine=create_engine("sqlite://")))
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/v1/auth/session").status_code == 200

    headers = _api_headers()
    required_import_headers = {
        "x-account-id",
        "x-effective-date",
        "x-source-label",
        "x-expected-account-revision",
        "idempotency-key",
        "x-replace-existing",
        "x-column-mapping",
        "x-statement-start",
        "x-statement-end",
        "x-reason",
        "x-file-name",
        "x-fund-format",
        "x-weight-unit",
    }
    assert required_import_headers <= headers
    assert {"origin", "sec-fetch-site", "content-type"} <= headers

    client_sources = (ROOT / "apps/web/src").rglob("*.ts*")
    client_headers: set[str] = set()
    for path in client_sources:
        client_headers.update(
            value.casefold()
            for value in re.findall(
                r"['\"](X-[A-Za-z0-9-]+|Idempotency-Key)['\"]\s*:",
                path.read_text(),
            )
        )
    assert client_headers <= headers | {"accept", "authorization", "content-type"}
