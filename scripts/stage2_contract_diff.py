"""Deterministic offline diff of retained Stage2 OpenAPI snapshots."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def changes(before, after, pointer=""):
    if isinstance(before, dict) and isinstance(after, dict):
        result = []
        for key in sorted(before.keys() | after.keys()):
            path = pointer + "/" + key.replace("~", "~0").replace("/", "~1")
            if key not in before:
                result.append({"path": path, "added": after[key]})
            elif key not in after:
                result.append({"path": path, "removed": before[key]})
            else:
                result.extend(changes(before[key], after[key], path))
        return result
    return [] if before == after else [{"path": pointer, "before": before, "after": after}]


if __name__ == "__main__":
    folder = ROOT / "docs/external"
    old = json.loads((folder / "pharmascan-api-openapi-0.8.0.json").read_text(encoding="utf-8"))
    new = json.loads((folder / "pharmascan-api-openapi-0.10.0.json").read_text(encoding="utf-8"))
    result = {
        "from": old["info"]["version"],
        "to": new["info"]["version"],
        "added_paths": sorted(new["paths"].keys() - old["paths"].keys()),
        "changes": changes(old, new),
    }
    (folder / "pharmascan-api-0.8.0-to-0.10.0.diff.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"{len(result['changes'])} contract changes; added paths: {result['added_paths']}")
