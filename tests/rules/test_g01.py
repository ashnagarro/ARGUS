"""G01 detects publicly accessible database instances."""

from dataclasses import replace

from argus.models import Change
from argus.rules.g01 import PublicDatabaseAccess


def _database(public: bool) -> Change:
    return Change(
        address="aws_db_instance.fake", resource_type="aws_db_instance",
        canonical_type="database_instance", actions=("create",),
        before=None, after={"publicly_accessible": public},
        replace_paths=(), tags={}, is_replace=False,
    )


def test_public_database_triggers() -> None:
    change = _database(True)

    findings = PublicDatabaseAccess().check(change, [change])

    assert len(findings) == 1
    assert findings[0].rule_id == "G01"
    assert findings[0].severity == "critical"
    assert findings[0].resource == change.address


def test_private_or_deleted_database_does_not_trigger() -> None:
    private = _database(False)
    deleted = replace(_database(True), actions=("delete",), after=None)

    assert PublicDatabaseAccess().check(private, [private]) == []
    assert PublicDatabaseAccess().check(deleted, [deleted]) == []
