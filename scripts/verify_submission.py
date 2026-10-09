"""Verify a committed-file submission ZIP before sharing it."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from zipfile import ZipFile


EXCLUDED_PARTS = {".venv", ".cache", ".terraform", "uploads", "keys"}
EXCLUDED_NAMES = {".env", ".env.local", "id_rsa", "id_ed25519"}
EXCLUDED_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".tfstate"}
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(rb"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{20,}\b"),
    re.compile(rb"(?im)^\s*(?:OPENAI_API_KEY|CODEX_API_KEY)\s*=\s*[A-Za-z0-9_-]{20,}\s*$"),
)
PLAN_CREDENTIAL = re.compile(
    rb'"(?:password|secret_key|access_key|api_key|private_key)"\s*:\s*"([^"\\]+)"',
    re.IGNORECASE,
)


def verify_zip(path: Path) -> tuple[int, int]:
    """Return member and scanned-file counts; raise for leaks or excluded paths."""
    scanned = 0
    with ZipFile(path) as package:
        names = package.namelist()
        for name in names:
            parts = [part.lower() for part in Path(name).parts]
            leaf = parts[-1] if parts else ""
            if (any(part in EXCLUDED_PARTS for part in parts) or leaf in EXCLUDED_NAMES
                    or any(leaf.endswith(suffix) for suffix in EXCLUDED_SUFFIXES)):
                raise ValueError(f"Excluded file in ZIP: {name}")
            if name.endswith("/"):
                continue
            content = package.read(name)
            scanned += 1
            for pattern in SECRET_PATTERNS:
                for match in pattern.finditer(content):
                    token = match.group(0).lower()
                    if any(marker in token for marker in (b"fake", b"synthetic", b"example")):
                        continue
                    raise ValueError(f"Secret pattern found in ZIP member: {name}")
            if name.lower().endswith(".json"):
                for match in PLAN_CREDENTIAL.finditer(content):
                    value = match.group(1).lower()
                    # The committed risky fixture intentionally contains fake credentials.
                    if b"fake" not in value and value not in (b"test", b"example", b"[redacted]"):
                        raise ValueError(f"Credential value found in ZIP member: {name}")
    return len(names), scanned


if __name__ == "__main__":
    try:
        members, scanned = verify_zip(Path(sys.argv[1]))
    except (IndexError, OSError, ValueError) as error:
        print(f"Submission verification: FAIL — {error}", file=sys.stderr)
        raise SystemExit(1)
    print(f"ZIP exclusions: PASS ({members} members)")
    print(f"Secret scan: PASS ({scanned} files scanned)")
