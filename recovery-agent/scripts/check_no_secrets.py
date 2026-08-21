"""
scripts/check_no_secrets.py — mental gitleaks for the hackathon repo.

Scans tracked-ish source for live-looking Razorpay secrets.
Exits non-zero if a real-looking key/secret appears outside .env.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Live test key ids look like rzp_test_ + 14 alnum (placeholder uses xxx)
KEY_ID = re.compile(r"rzp_test_[A-Za-z0-9]{10,}")
# Generic secret assignment in source
SECRET_ASSIGN = re.compile(
    r"(RAZORPAY_KEY_SECRET|key_secret)\s*=\s*['\"](?!xxx)[A-Za-z0-9]{16,}['\"]"
)

SKIP_PARTS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "data",
    "node_modules",
    ".env",  # file name match handled below
}

ALLOW_SUBSTRINGS = (
    "rzp_test_xxx",
    "rzp_test_real",  # unit-test mocks
)


def should_skip(path: Path) -> bool:
    if path.name == ".env":
        return True
    parts = set(path.parts)
    if parts & SKIP_PARTS:
        return True
    if path.suffix not in {".py", ".md", ".yml", ".yaml", ".json", ".toml", ".txt", ".html", ".css", ".example"}:
        return True
    return False


def is_allowed(text: str) -> bool:
    return any(a in text for a in ALLOW_SUBSTRINGS)


def main() -> int:
    bad: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or should_skip(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for m in KEY_ID.finditer(text):
            token = m.group(0)
            if is_allowed(token) or token.endswith("xxx"):
                continue
            # .env.example placeholder pattern
            if "xxx" in token:
                continue
            bad.append(f"{rel}: possible key_id {token}")
        for m in SECRET_ASSIGN.finditer(text):
            bad.append(f"{rel}: possible secret assignment")

    if bad:
        print("SECRET CHECK FAILED:")
        for line in bad:
            print(" ", line)
        return 1
    print("secret check ok (no live-looking keys in source)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
