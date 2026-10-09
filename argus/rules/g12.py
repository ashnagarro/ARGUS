"""G12: public ingress to SSH or RDP ports."""

from collections.abc import Sequence
from typing import Any

from argus.models import Change, RuleFinding
from argus.rules import Rule


_MANAGEMENT_PORTS = (22, 3389)
_PUBLIC_CIDRS = ("0.0.0.0/0", "::/0")


def _public_cidr(ingress: dict[str, Any]) -> str | None:
    values: list[object] = []
    for field in ("cidr_blocks", "ipv6_cidr_blocks"):
        raw = ingress.get(field)
        if isinstance(raw, (list, tuple)):
            values.extend(raw)
        elif isinstance(raw, str):
            values.append(raw)
    values.extend((ingress.get("cidr_ipv4"), ingress.get("cidr_ipv6")))
    return next((cidr for cidr in _PUBLIC_CIDRS if cidr in values), None)


def _ports(ingress: dict[str, Any]) -> tuple[int, ...]:
    protocol = ingress.get("protocol", ingress.get("ip_protocol"))
    if protocol in ("-1", -1):
        return _MANAGEMENT_PORTS
    if protocol not in ("tcp", "6", 6):
        return ()
    start = ingress.get("from_port")
    end = ingress.get("to_port")
    if (type(start) is not int or type(end) is not int or end < start):
        return ()
    return tuple(port for port in _MANAGEMENT_PORTS if start <= port <= end)


class PublicManagementPort(Rule):
    id = "G12"
    title = "Management port open to the internet"
    severity = "high"
    why_it_matters = "Public SSH or RDP ingress exposes management services to internet traffic."
    how_to_fix = "Restrict the ingress CIDR to an approved private network or use a managed access path."

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        after = change.after
        if after is None:
            return []
        if change.resource_type == "aws_security_group_rule":
            entries = [after] if after.get("type") == "ingress" else []
        elif change.resource_type == "aws_vpc_security_group_ingress_rule":
            entries = [after]
        elif change.resource_type == "aws_security_group":
            raw_entries = after.get("ingress")
            entries = raw_entries if isinstance(raw_entries, list) else []
        else:
            return []
        exposed: set[tuple[int, str]] = set()
        for entry in entries:
            if isinstance(entry, dict):
                cidr = _public_cidr(entry)
                if cidr is not None:
                    exposed.update((port, cidr) for port in _ports(entry))
        return [self.finding(change, f"Ingress permits management port {port} from {cidr}.")
                for port, cidr in sorted(exposed)]
