"""Ground Truth Claim 的声明级存储与冻结。"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GroundTruthClaim:
    claim_id: str
    claim: str
    source: str
    url: str
    date: str
    region: str
    metric: str
    unit: str
    evidence_excerpt: str
    confidence: str
    verification_status: str
    verification_sources: tuple[str, ...] = ()
    verification_contexts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        required = {
            "claim_id": self.claim_id,
            "claim": self.claim,
            "source": self.source,
            "url": self.url,
            "date": self.date,
            "region": self.region,
            "evidence_excerpt": self.evidence_excerpt,
            "confidence": self.confidence,
            "verification_status": self.verification_status,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"missing ground truth fields: {', '.join(missing)}")
        if self.verification_status not in {"VERIFIED", "DISPUTED", "UNVERIFIED"}:
            raise ValueError(f"unsupported verification_status: {self.verification_status}")
        if any(not value for value in self.verification_sources):
            raise ValueError("verification_sources must not contain empty values")
        if any(not value for value in self.verification_contexts):
            raise ValueError("verification_contexts must not contain empty values")

    def to_dict(self) -> dict[str, str]:
        return {
            "claim_id": self.claim_id,
            "claim": self.claim,
            "source": self.source,
            "url": self.url,
            "date": self.date,
            "region": self.region,
            "metric": self.metric,
            "unit": self.unit,
            "evidence_excerpt": self.evidence_excerpt,
            "confidence": self.confidence,
            "verification_status": self.verification_status,
            "verification_sources": list(self.verification_sources),
            "verification_contexts": list(self.verification_contexts),
        }

    @classmethod
    def from_dict(cls, value: dict[str, str]) -> GroundTruthClaim:
        data = dict(value)
        data["verification_sources"] = tuple(data.get("verification_sources", ()))
        data["verification_contexts"] = tuple(data.get("verification_contexts", ()))
        return cls(**data)


@dataclass(frozen=True)
class GroundTruthBundle:
    claims: list[GroundTruthClaim]
    source_hash: str


class GroundTruthStore:
    @staticmethod
    def write(path: Path, claims: list[GroundTruthClaim]) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        content = "\n".join(
            json.dumps(claim.to_dict(), ensure_ascii=False, sort_keys=True) for claim in claims
        )
        Path(path).write_text(content + ("\n" if content else ""), encoding="utf-8")

    @staticmethod
    def load(path: Path) -> list[GroundTruthClaim]:
        claims: list[GroundTruthClaim] = []
        seen: set[str] = set()
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            claim = GroundTruthClaim.from_dict(json.loads(line))
            if claim.claim_id in seen:
                raise ValueError(f"duplicate claim_id: {claim.claim_id}")
            seen.add(claim.claim_id)
            claims.append(claim)
        return claims

    @classmethod
    def freeze(
        cls,
        path: Path,
        *,
        require_cross_verification: bool = False,
    ) -> GroundTruthBundle:
        claims = cls.load(path)
        if require_cross_verification:
            cls.validate_cross_verification(claims)
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        return GroundTruthBundle(claims=claims, source_hash=digest)

    @classmethod
    def freeze_verified(
        cls,
        path: Path,
        manifest_path: Path,
        *,
        require_cross_verification: bool = True,
    ) -> GroundTruthBundle:
        """Freeze a formal Ground Truth file only when its manifest hash matches."""
        try:
            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read ground truth manifest: {manifest_path}") from exc
        if not isinstance(manifest, dict):
            raise ValueError("ground truth manifest must be an object")
        if manifest.get("status") != "FROZEN_FORMAL_MINIMUM_TARGET":
            raise ValueError("ground truth manifest is not frozen formal target")
        if manifest.get("formal_ground_truth") is not True:
            raise ValueError("ground truth manifest is not marked formal")
        expected_hash = manifest.get("source_hash")
        if not isinstance(expected_hash, str) or not expected_hash:
            raise ValueError("ground truth manifest source_hash is required")
        bundle = cls.freeze(path, require_cross_verification=require_cross_verification)
        if bundle.source_hash != expected_hash:
            raise ValueError("ground truth manifest hash mismatch")
        return bundle

    @staticmethod
    def validate_cross_verification(claims: list[GroundTruthClaim]) -> None:
        if not claims:
            raise ValueError("formal ground truth must contain at least one claim")
        for claim in claims:
            if claim.verification_status == "UNVERIFIED":
                raise ValueError(
                    f"claim {claim.claim_id} is UNVERIFIED and cannot enter formal ground truth"
                )
            if len(set(claim.verification_sources)) < 2:
                raise ValueError(
                    f"claim {claim.claim_id} requires two verification sources"
                )
            if len(set(claim.verification_contexts)) < 2:
                raise ValueError(
                    f"claim {claim.claim_id} requires two verification contexts"
                )
