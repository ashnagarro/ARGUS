"""Synthetic positive and negative cases for G19."""

from argus.models import Change
from argus.rules.g19 import G19S3VersioningSuspended


def _change(before: str, after: str | None) -> Change:
    prior = {"versioning_configuration": [{"status": before}]}
    proposed = {"versioning_configuration": [{"status": after}]} if after else None
    return Change("aws_s3_bucket_versioning.sample", "aws_s3_bucket_versioning",
                  "aws_s3_bucket_versioning", ("update",) if after else ("delete",),
                  prior, proposed, (), {}, False)


def test_g19_flags_suspension_and_deletion_of_enabled_versioning() -> None:
    rule = G19S3VersioningSuspended()
    for change in (_change("Enabled", "Suspended"), _change("Enabled", None)):
        assert [item.rule_id for item in rule.check(change, (change,))] == ["G19"]


def test_g19_ignores_enabled_versioning_or_unversioned_deletion() -> None:
    rule = G19S3VersioningSuspended()
    for change in (_change("Enabled", "Enabled"), _change("Disabled", None)):
        assert rule.check(change, (change,)) == []
