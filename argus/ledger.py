"""Preserve completed ledger sessions in timestamped local archives."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def archive_ledger(root: Path, *, now: datetime | None = None) -> Path | None:
    """Move the current ledger, run records, and traces into one archive."""
    ledger = Path(root) / "ledger"
    sources = [ledger / name for name in ("ledger.jsonl", "runs", "traces")]
    existing = [path for path in sources if path.exists()]
    if not existing:
        return None

    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stem = timestamp.strftime("%Y%m%dT%H%M%S%fZ")
    archive_root = ledger / "archive"
    archive_root.mkdir(parents=True, exist_ok=True)
    number = 1
    while True:
        name = stem if number == 1 else f"{stem}-{number}"
        destination = archive_root / name
        try:
            destination.mkdir()
            break
        except FileExistsError:
            number += 1

    moved: list[tuple[Path, Path]] = []
    try:
        for source in existing:
            target = destination / source.name
            source.rename(target)
            moved.append((source, target))
    except OSError:
        for source, target in reversed(moved):
            target.rename(source)
        raise
    return destination
