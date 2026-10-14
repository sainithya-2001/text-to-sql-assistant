"""Fail if a Dify export looks unsanitized.

Rule-based on purpose: this file is committed, so it must not contain the secrets it guards against.

Usage: python scripts/check_sanitized.py [DIR_OR_FILES...]   (default: prototype-sanitized/)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PLACEHOLDER = re.compile(r"^<[A-Z0-9_]+>$")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
SECRET_PATTERNS = {
    "api key": re.compile(r"\b(sk-[A-Za-z0-9_-]{16,}|sk-ant-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16})"),
    "url with credentials": re.compile(r"[a-z]+://[^/\s:@]+:[^/\s@]+@"),
    "snowflake host": re.compile(r"[a-z0-9-]+\.snowflakecomputing\.com", re.I),
}


def check_text(name: str, text: str) -> list[str]:
    problems: list[str] = []
    lines = text.splitlines()

    for i, line in enumerate(lines):
        # if-else condition values compared against a *password* variable must be placeholders.
        # Dify writes `value:` a few lines above `variable_selector: [node, <var>]`.
        m = re.match(r"\s*value:\s*(.+?)\s*$", line)
        if m:
            window = "\n".join(lines[i : i + 6]).lower()
            if "variable_selector" in window and ("password" in window or "passwd" in window):
                val = m.group(1).strip("'\"")
                if not PLACEHOLDER.match(val):
                    problems.append(f"{name}:{i + 1}: password condition has a literal value")

        # Dify knowledge-base IDs: list item directly under `dataset_ids:`
        if line.strip() == "dataset_ids:":
            for j in range(i + 1, len(lines)):
                item = lines[j].strip()
                if not item.startswith("- "):
                    break
                if not PLACEHOLDER.match(item[2:].strip()):
                    problems.append(f"{name}:{j + 1}: unredacted dataset id")

        # comparisons against sys.user_id must not contain a real id
        if "sys.user_id" in line:
            for k in range(i, min(i + 2, len(lines))):
                if UUID.search(lines[k]) or re.search(r'=="\d+"', lines[k]):
                    problems.append(f"{name}:{k + 1}: user id in sys.user_id comparison")

        for label, pat in SECRET_PATTERNS.items():
            if pat.search(line):
                problems.append(f"{name}:{i + 1}: looks like {label}")

    return sorted(set(problems))


def main(argv: list[str]) -> int:
    targets = [Path(a) for a in argv] or [Path("prototype-sanitized")]
    files: list[Path] = []
    for t in targets:
        files.extend(sorted(t.glob("*.yml")) + sorted(t.glob("*.yaml")) if t.is_dir() else [t])
    if not files:
        print("no files to check", file=sys.stderr)
        return 1
    problems = [p for f in files for p in check_text(f.name, f.read_text(encoding="utf-8"))]
    for p in problems:
        print(p)
    print(f"checked {len(files)} file(s): {'FAIL' if problems else 'ok'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
