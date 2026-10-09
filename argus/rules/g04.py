"""G04: S3 server-side encryption configuration deleted."""

from typing import Sequence

from argus.models import Change, RuleFinding
from argus.rules import Rule


class S3EncryptionConfigurationDeleted(Rule):
    id = "G04"
    title = "S3 encryption configuration deleted"
    severity = "high"
    why_it_matters = "Removing bucket encryption configuration can leave new objects without the expected encryption policy."
    how_to_fix = "Keep the bucket server-side encryption configuration or replace it in the same change."

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        if (change.resource_type == "aws_s3_bucket_server_side_encryption_configuration"
                and "delete" in change.actions and "create" not in change.actions):
            return [self.finding(change, "S3 server-side encryption configuration is deleted.")]
        return []
