"""R004: public ingress to a database port."""

from collections.abc import Sequence
from typing import Any

from argus.models import Change
from argus.rules import Rule, RuleFinding


_DATABASE_PORTS = (1433, 3306, 5432)
_PUBLIC_CIDRS = ("0.0.0.0/0", "::/0")


def _public_database_ports(ingress: dict[str, Any]) -> tuple[tuple[int, str], ...]:
    cidrs: list[object] = []
    for field in ("cidr_blocks", "ipv6_cidr_blocks"):
        raw = ingress.get(field)
        if isinstance(raw, (list, tuple)):
            cidrs.extend(raw)
        elif isinstance(raw, str):
            cidrs.append(raw)
    cidrs.extend((ingress.get("cidr_ipv4"), ingress.get("cidr_ipv6")))
    public_cidrs = tuple(cidr for cidr in _PUBLIC_CIDRS if cidr in cidrs)
    if not public_cidrs:
        return ()

    protocol = ingress.get("protocol", ingress.get("ip_protocol"))
    if protocol in ("-1", -1):
        return tuple((port, cidr) for port in _DATABASE_PORTS for cidr in public_cidrs)
    if protocol not in ("tcp", "6", 6):
        return ()

    start = ingress.get("from_port")
    end = ingress.get("to_port")
    if not isinstance(start, int) or isinstance(start, bool):
        return ()
    if not isinstance(end, int) or isinstance(end, bool) or end < start:
        return ()
    return tuple((port, cidr) for port in _DATABASE_PORTS if start <= port <= end
                 for cidr in public_cidrs)


class R004PublicDatabasePort(Rule):
    id = "R004"
    name = "data-port-exposed-to-internet"
    title = "Data service port open to the public internet"
    applies_to = ("terraform/aws",)
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

        if change.canonical_type != "network_ingress":
            return []
        raw_entries = after.get("ingress")
        if isinstance(raw_entries, list):
            entries = raw_entries
        else:
            entries = [after] if after.get("type") in (None, "ingress") else []

        exposed: set[tuple[int, str]] = set()
        for entry in entries:
            if isinstance(entry, dict):
                exposed.update(_public_database_ports(entry))
        return [
            self.finding(change, f"Ingress permits database port {port} from {cidr}.")
            for port, cidr in sorted(exposed)
        ]
