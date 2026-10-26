"""证据质量与事实核验模块。"""
from .graph import (
    ClaimChain,
    ClaimRelationKind,
    EvidenceGraphStore,
    EvidenceSpanRecord,
    FindingRecord,
    SourceSnapshotRecord,
    VerificationStatus,
)
from .ledger import EvidenceLedger, build_evidence_ledger
from .store import EvidenceStore
from .verifier import FactVerifier, VerificationReport

__all__ = [
    "ClaimChain",
    "ClaimRelationKind",
    "EvidenceGraphStore",
    "EvidenceLedger",
    "EvidenceSpanRecord",
    "EvidenceStore",
    "FactVerifier",
    "FindingRecord",
    "SourceSnapshotRecord",
    "VerificationReport",
    "VerificationStatus",
    "build_evidence_ledger",
]
