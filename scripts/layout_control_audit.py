from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKS_DIR = ROOT / "content" / "works"
META_DIR = ROOT / ".stillmrk-build" / "meta"

TOKENS = {"auto", "quiet", "standard", "medium", "large", "wide", "full"}
ALIASES = {
    "small": "quiet",
    "compact": "quiet",
    "normal": "standard",
    "default": "standard",
    "regular": "standard",
    "feature": "large",
    "featured": "large",
    "hero": "wide",
    "cinematic": "wide",
    "span": "wide",
}
RATIO_KEYS = {"default", "portfolio", "series", "hero", "cover", "about"}
LAYOUT_KEYS = {"portfolio", "series"}


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return {"__error__": str(exc)}
    return data if isinstance(data, dict) else {"__error__": "YAML root is not an object"}


def normalize_token(value: Any) -> str:
    token = str(value or "").strip().lower().replace("_", "-")
    token = ALIASES.get(token, token)
    return token


def audit() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    used_tokens: dict[str, int] = {}

    for path in sorted(WORKS_DIR.glob("*.yaml")):
        data = load_yaml(path)
        work_id = str(data.get("id") or path.stem).strip()
        if data.get("__error__"):
            rows.append({"work_id": work_id, "file": str(path.relative_to(ROOT)), "status": "error", "detail": data["__error__"]})
            continue

        row: dict[str, Any] = {
            "work_id": work_id,
            "file": str(path.relative_to(ROOT)),
            "portfolio_layout": str(data.get("portfolio_layout") or data.get("portfolioLayout") or "auto").strip() or "auto",
            "series_layout": str(data.get("series_layout") or data.get("seriesLayout") or "auto").strip() or "auto",
            "status": "ok",
            "warnings": [],
        }

        for field in ("portfolio_layout", "series_layout"):
            raw_value = row[field]
            token = normalize_token(raw_value)
            if raw_value and token not in TOKENS:
                row["warnings"].append(f"{field} has unsupported token '{raw_value}'")
            else:
                canonical = token if token in TOKENS else "auto"
                used_tokens[canonical] = used_tokens.get(canonical, 0) + 1

        display_layouts = data.get("display_layouts")
        if isinstance(display_layouts, dict):
            for key, value in display_layouts.items():
                if key not in LAYOUT_KEYS:
                    row["warnings"].append(f"display_layouts.{key} is not a supported context")
                token = normalize_token(value)
                if value and token not in TOKENS:
                    row["warnings"].append(f"display_layouts.{key} has unsupported token '{value}'")

        display_ratios = data.get("display_ratios")
        if isinstance(display_ratios, dict):
            for key, value in display_ratios.items():
                if key not in RATIO_KEYS:
                    row["warnings"].append(f"display_ratios.{key} is not a supported context")
                if value is not None and not isinstance(value, str):
                    row["warnings"].append(f"display_ratios.{key} should be a string like '4 / 3'")

        if row["warnings"]:
            row["status"] = "warning"
            warnings.extend(f"{work_id}: {item}" for item in row["warnings"])

        rows.append(row)

    return {
        "status": "PASS_WITH_WARNINGS" if warnings else "PASS",
        "warnings": len(warnings),
        "used_tokens": dict(sorted(used_tokens.items())),
        "rows": rows,
        "warning_details": warnings,
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Layout Control Report",
        "",
        f"Status: `{report['status']}`",
        f"Warnings: `{report['warnings']}`",
        "",
        "## Token use",
        "",
    ]
    for token, count in report.get("used_tokens", {}).items():
        lines.append(f"- `{token}`: {count}")
    lines.extend(["", "## Warnings", ""])
    if report.get("warning_details"):
        for warning in report["warning_details"]:
            lines.append(f"- {warning}")
    else:
        lines.append("No layout-token warnings.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    META_DIR.mkdir(parents=True, exist_ok=True)
    report = audit()
    json_path = META_DIR / "layout-control-report.json"
    md_path = ROOT / "LAYOUT_CONTROL_REPORT.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_markdown(report, md_path)
    print(f"Layout control audit: {report['status']} · warnings={report['warnings']}")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
