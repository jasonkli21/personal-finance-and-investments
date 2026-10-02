"""Export the API schema used to generate the web client's TypeScript types."""

import json
import sys
from pathlib import Path

from app.main import app


def main() -> None:
    output = (
        Path(sys.argv[1]).resolve()
        if len(sys.argv) > 1
        else Path(__file__).resolve().parents[3]
        / "apps"
        / "web"
        / "src"
        / "api"
        / "openapi.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
