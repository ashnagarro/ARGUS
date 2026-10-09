"""R004: public ingress to a database port."""

from collections.abc import Sequence
from typing import Any

from argus.models import Change
from argus.rules import Rule, RuleFinding


_DATABASE_PORTS = (1433, 3306, 5432)


def _public_database_ports(ingress: dict[str, Any]) -> tuple[int, ...]:
    cidrs = ingress.get("cidr_blocks")
    if not isinstance(cidrs, (list, tuple)) or "0.0.0.0/0" not in cidrs:
        return ()

    protocol = ingress.get("protocol")
    if protocol in ("-1", -1):
        return _DATABASE_PORTS
    if protocol not in ("tcp", "6", 6):
        return ()

    start = ingress.get("from_port")
    end = ingress.get("to_port")
    if not isinstance(start, int) or isinstance(start, bool):
        return ()
    if not isinstance(end, int) or isinstance(end, bool) or end < start:
        return ()
    return tuple(port for port in _DATABASE_PORTS if start <= port <= end)


class R004PublicDatabasePort(Rule):
    id = "R004"
    title = "Database port open to the internet"
    severity = "high"
    controls = ()
    source_doc_ids = ()
    why_it_matters = "A public database port exposes the service to connections from the internet."
    how_to_fix = "Replace 0.0.0.0/0 in cidr_blocks with the approved private CIDR ranges."

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        """Check planned ingress on a security group or ingress rule."""
        after = change.after
        if after is None:
            return []

        if change.canonical_type == "network_security_rule":
            entries = [after] if after.get("type") == "ingress" else []
        elif change.canonical_type == "network_security_group":
            raw_entries = after.get("ingress")
            entries = raw_entries if isinstance(raw_entries, list) else []
        else:
            return []

        ports: set[int] = set()
        for entry in entries:
            if isinstance(entry, dict):
                ports.update(_public_database_ports(entry))
        return [
            self.finding(change, f"Ingress permits database port {port} from 0.0.0.0/0.")
            for port in sorted(ports)
        ]
