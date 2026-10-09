"""G17: CloudWatch log retention falls below an explicit organization minimum."""

from collections.abc import Sequence

from argus.models import Change, RuleFinding
from argus.rules import Rule


class G17LogRetentionBelowMinimum(Rule):
    id = "G17"
    name = "log-retention-below-minimum"
    title = "Log retention below required minimum"
    applies_to = ("terraform/aws",)
    severity = "high"
    why_it_matters = "Short retention can remove logs before an investigation or audit needs them."
    how_to_fix = "Set retention_in_days to at least the organization's configured minimum, or 0 for indefinite retention."

    def __init__(self, minimum_retention_days: int | None = None) -> None:
        if minimum_retention_days is not None and (
            type(minimum_retention_days) is not int or minimum_retention_days <= 0
        ):
            raise ValueError("minimum_retention_days must be a positive integer")
        self.minimum_retention_days = minimum_retention_days

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        if change.resource_type != "aws_cloudwatch_log_group" or self.minimum_retention_days is None:
            return []
        after = change.after or {}
        days = after.get("retention_in_days")
        if type(days) is int and 0 < days < self.minimum_retention_days:
            return [self.finding(
                change,
                f"Log retention is {days} days, below the configured {self.minimum_retention_days}-day minimum.",
            )]
        return []
