"""Safe, read-only local and allowlisted remote network checks."""

import ipaddress
import socket
import ssl
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from .policy import NetworkPolicy, load_policy


class NetworkPolicyError(ValueError):
    pass


def _run_local(command: List[str]) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5, check=False)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "local network command failed")
    return completed.stdout[:20000]


def check_local_state() -> Dict[str, Any]:
    """Return local adapter, route and listener information without egress."""
    try:
        if __import__("os").name == "nt":
            return {
                "status": "ok",
                "scope": "local_readonly",
                "ip_configuration": _run_local(["ipconfig", "/all"]),
                "listening_ports": _run_local(["netstat", "-ano"]),
            }
        return {"status": "ok", "scope": "local_readonly", "ip_configuration": _run_local(["ip", "addr"]), "routes": _run_local(["ip", "route"])}
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        return {"status": "network_error", "scope": "local_readonly", "error": str(exc)}


def _validate_target(target: str, port: int, policy: NetworkPolicy) -> List[Tuple[int, str]]:
    normalized = target.lower().rstrip(".")
    if normalized not in policy.allowed_hosts:
        raise NetworkPolicyError("target is not in config/network_policy.yaml allowed_hosts")
    if port not in policy.allowed_ports:
        raise NetworkPolicyError("port is not in config/network_policy.yaml allowed_ports")
    try:
        records = socket.getaddrinfo(normalized, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise NetworkPolicyError(f"DNS resolution failed: {exc}") from exc
    addresses: List[Tuple[int, str]] = []
    for family, _, _, _, sockaddr in records:
        address = sockaddr[0]
        ip = ipaddress.ip_address(address)
        is_private = ip.is_private or ip.is_loopback or ip.is_link_local
        if is_private and not policy.allow_private_addresses:
            raise NetworkPolicyError("resolved address is private but private addresses are disabled")
        if not is_private and not policy.allow_public_addresses:
            raise NetworkPolicyError("resolved address is public but public addresses are disabled")
        if (family, address) not in addresses:
            addresses.append((family, address))
    if not addresses:
        raise NetworkPolicyError("target did not resolve to a permitted address")
    return addresses


def check_dns(target: str) -> Dict[str, Any]:
    try:
        policy = load_policy()
        # DNS queries do not connect to the target, but require an explicit host allowlist.
        if target.lower().rstrip(".") not in policy.allowed_hosts:
            raise NetworkPolicyError("target is not in config/network_policy.yaml allowed_hosts")
        records = socket.getaddrinfo(target, None)
        addresses = sorted({item[4][0] for item in records})
        return {"status": "ok", "check": "dns", "target": target, "addresses": addresses}
    except (OSError, ValueError, NetworkPolicyError) as exc:
        return {"status": "network_error", "check": "dns", "error": str(exc)}


def check_tcp(target: str, port: int) -> Dict[str, Any]:
    try:
        policy = load_policy()
        addresses = _validate_target(target, port, policy)
        family, address = addresses[0]
        with socket.socket(family, socket.SOCK_STREAM) as connection:
            connection.settimeout(policy.timeout_seconds)
            started = datetime.now(timezone.utc)
            connection.connect((address, port))
        elapsed_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
        return {"status": "ok", "check": "tcp", "target": target, "address": address, "port": port, "latency_ms": round(elapsed_ms, 1)}
    except (OSError, ValueError, NetworkPolicyError) as exc:
        return {"status": "network_error", "check": "tcp", "error": str(exc)}


def check_tls(target: str, port: int = 443) -> Dict[str, Any]:
    try:
        policy = load_policy()
        addresses = _validate_target(target, port, policy)
        family, address = addresses[0]
        context = ssl.create_default_context()
        with socket.socket(family, socket.SOCK_STREAM) as connection:
            connection.settimeout(policy.timeout_seconds)
            connection.connect((address, port))
            with context.wrap_socket(connection, server_hostname=target) as secured:
                certificate = secured.getpeercert()
                protocol = secured.version()
        return {
            "status": "ok",
            "check": "tls",
            "target": target,
            "address": address,
            "port": port,
            "protocol": protocol,
            "expires_at": certificate.get("notAfter"),
            "subject": certificate.get("subject"),
        }
    except (OSError, ValueError, ssl.SSLError, NetworkPolicyError) as exc:
        return {"status": "network_error", "check": "tls", "error": str(exc)}
