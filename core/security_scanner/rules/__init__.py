from .base import BaseRule
from .r1_credential_leak import R1CredentialLeak
from .r2_command_injection import R2CommandInjection
from .r3_filesystem_risk import R3FilesystemRisk
from .r4_network_risk import R4NetworkRisk
from .r5_privilege_escalation import R5PrivilegeEscalation
from .r6_data_exfiltration import R6DataExfiltration
from .r7_manifest_integrity import R7ManifestIntegrity
from .r8_permission_consistency import R8PermissionConsistency
from .r9_unsigned_script import R9UnsignedScript
from .r10_delegation_chain import R10DelegationChain

ALL_RULES = [
    R1CredentialLeak,
    R2CommandInjection,
    R3FilesystemRisk,
    R4NetworkRisk,
    R5PrivilegeEscalation,
    R6DataExfiltration,
    R7ManifestIntegrity,
    R8PermissionConsistency,
    R9UnsignedScript,
    R10DelegationChain,
]

__all__ = [
    "BaseRule",
    "R1CredentialLeak",
    "R2CommandInjection",
    "R3FilesystemRisk",
    "R4NetworkRisk",
    "R5PrivilegeEscalation",
    "R6DataExfiltration",
    "R7ManifestIntegrity",
    "R8PermissionConsistency",
    "R9UnsignedScript",
    "R10DelegationChain",
    "ALL_RULES",
]
