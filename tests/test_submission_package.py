"""Submission ZIP rejects secret-like payloads and private work directories."""

from pathlib import Path
from zipfile import ZipFile

import pytest

from scripts.verify_submission import verify_zip


def _zip(path: Path, member: str, payload: bytes) -> Path:
    with ZipFile(path, "w") as package:
        package.writestr(member, payload)
    return path


def test_submission_verifier_accepts_marked_fake_fixture(tmp_path):
    path = _zip(tmp_path / "safe.zip", "fixtures/plans/test.json",
                b'{"password":"Sup3rSecret-FAKE-123"}')
    assert verify_zip(path) == (1, 1)


@pytest.mark.parametrize("member,payload", [
    (".venv/Lib/site.py", b"safe"),
    ("ledger/uploads/plan.json", b"{}"),
    ("infra/.terraform/provider", b"safe"),
    ("credentials.pem", b"safe"),
    ("plan.json", b'{"password":"realcredential123456"}'),
    ("readme.txt", b"-----BEGIN " + b"PRIVATE KEY-----"),
])
def test_submission_verifier_rejects_exclusions_and_secrets(tmp_path, member, payload):
    path = _zip(tmp_path / "unsafe.zip", member, payload)
    with pytest.raises(ValueError):
        verify_zip(path)
