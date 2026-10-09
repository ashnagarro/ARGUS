"""G02: disabled S3 public access blocks."""

from typing import Sequence

from argus.models import Change, RuleFinding
from argus.rules import Rule


class S3PublicAccessBlockDisabled(Rule):
    id = "G02"
    title = "S3 public access block disabled"
    severity = "high"
    why_it_matters = "Disabled S3 public access controls can allow bucket or object exposure."
    how_to_fix = "Set all four S3 public access block settings to true."

    _settings = (
        "block_public_acls",
        "ignore_public_acls",
        "block_public_policy",
        "restrict_public_buckets",
    )

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        if change.resource_type != "aws_s3_bucket_public_access_block" or change.after is None:
            return []
        disabled = [name for name in self._settings if change.after.get(name) is False]
        if disabled:
            return [self.finding(change, f"S3 public access block disabled: {', '.join(disabled)}.")]
        return []
