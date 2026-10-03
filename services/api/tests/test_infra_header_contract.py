"""Keep API and browser headers reachable through the CloudFront API behavior."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from sqlalchemy import create_engine

from app.main import create_app

ROOT = Path(__file__).resolve().parents[3]
MANAGED_ALL_VIEWER_EXCEPT_HOST = "b689b0a8-53d0-40ab-baf2-68738e2966ac"


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


def test_cloudfront_forwards_every_openapi_and_manually_read_header() -> None:
    terraform = (ROOT / "infra/terraform/main.tf").read_text()
    api_behavior = terraform.split("ordered_cache_behavior {", 1)[1]
    api_behavior = api_behavior.split("\n  }\n\n  restrictions", 1)[0]
    assert re.search(r'path_pattern\s*=\s*"/api/\*"', api_behavior)
    assert MANAGED_ALL_VIEWER_EXCEPT_HOST in api_behavior
    assert "aws_cloudfront_origin_request_policy.api" not in api_behavior

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
