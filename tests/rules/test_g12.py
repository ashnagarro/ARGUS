"""G12 catches public SSH and RDP ingress."""

import pytest

from argus.models import Change
from argus.rules.g12 import PublicManagementPort


def _change(resource_type: str, after: dict) -> Change:
    return Change(
        address=f"{resource_type}.synthetic", resource_type=resource_type,
        canonical_type=resource_type, actions=("create",),
        before=None, after=after, replace_paths=(), tags={},
        is_replace=False,
    )


@pytest.mark.parametrize(("resource_type", "after", "port"), [
    ("aws_security_group_rule", {
        "type": "ingress", "protocol": "tcp", "from_port": 22,
        "to_port": 22, "cidr_blocks": ["0.0.0.0/0"],
    }, 22),
    ("aws_vpc_security_group_ingress_rule", {
        "ip_protocol": "tcp", "from_port": 3389,
        "to_port": 3389, "cidr_ipv6": "::/0",
    }, 3389),
    ("aws_security_group", {"ingress": [{
        "protocol": "-1", "from_port": 0, "to_port": 0,
        "ipv6_cidr_blocks": ["::/0"],
    }]}, 22),
])
def test_public_management_ingress_triggers(
    resource_type: str, after: dict, port: int,
) -> None:
    change = _change(resource_type, after)
    findings = PublicManagementPort().check(change, [change])
    assert findings
    assert all(finding.rule_id == "G12" for finding in findings)
    assert any(str(port) in finding.message for finding in findings)


def test_private_ingress_and_public_egress_do_not_trigger() -> None:
    rule = PublicManagementPort()
    private = _change("aws_security_group_rule", {
        "type": "ingress", "protocol": "tcp", "from_port": 22,
        "to_port": 22, "cidr_blocks": ["10.0.0.0/8"],
    })
    egress = _change("aws_security_group_rule", {
        "type": "egress", "protocol": "tcp", "from_port": 3389,
        "to_port": 3389, "cidr_blocks": ["0.0.0.0/0"],
    })
    assert rule.check(private, [private]) == []
    assert rule.check(egress, [egress]) == []
