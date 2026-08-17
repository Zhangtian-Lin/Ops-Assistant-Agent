"""Network egress policy. Missing configuration permits local observations only."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, FrozenSet

import yaml

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
POLICY_FILE = WORKSPACE_ROOT / "config" / "network_policy.yaml"


@dataclass(frozen=True)
class NetworkPolicy:
    allowed_hosts: FrozenSet[str]
    allowed_ports: FrozenSet[int]
    timeout_seconds: float
    allow_private_addresses: bool
    allow_public_addresses: bool


def load_policy() -> NetworkPolicy:
    if not POLICY_FILE.exists():
        return NetworkPolicy(frozenset(), frozenset(), 5.0, True, False)
    with POLICY_FILE.open("r", encoding="utf-8") as stream:
        config: Dict[str, Any] = yaml.safe_load(stream) or {}
    network = config.get("network", {})
    if not isinstance(network, dict):
        raise ValueError("network_policy.yaml must contain a network mapping")
    hosts = network.get("allowed_hosts", [])
    ports = network.get("allowed_ports", [])
    if not isinstance(hosts, list) or not all(isinstance(item, str) for item in hosts):
        raise ValueError("allowed_hosts must be a list of hostnames or IP addresses")
    if not isinstance(ports, list) or not all(isinstance(item, int) and 1 <= item <= 65535 for item in ports):
        raise ValueError("allowed_ports must be a list of valid TCP ports")
    timeout = float(network.get("timeout_seconds", 5))
    if not 1 <= timeout <= 10:
        raise ValueError("timeout_seconds must be between 1 and 10")
    return NetworkPolicy(
        allowed_hosts=frozenset(item.lower().rstrip(".") for item in hosts),
        allowed_ports=frozenset(ports),
        timeout_seconds=timeout,
        allow_private_addresses=bool(network.get("allow_private_addresses", True)),
        allow_public_addresses=bool(network.get("allow_public_addresses", False)),
    )
