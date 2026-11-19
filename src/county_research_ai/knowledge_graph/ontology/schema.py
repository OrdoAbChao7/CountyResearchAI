"""产业知识本体约束：实体类型 × 关系类型 × 实体类型的合法签名。"""
from __future__ import annotations

from dataclasses import dataclass, field

from .entities import EntityType, KGEntity
from .relations import KGRelation, RelationshipType


@dataclass(frozen=True)
class RelationSignature:
    sources: frozenset[EntityType]
    targets: frozenset[EntityType]
    description: str = ""


def _sig(
    sources: tuple[EntityType, ...], targets: tuple[EntityType, ...], description: str = ""
) -> RelationSignature:
    return RelationSignature(frozenset(sources), frozenset(targets), description)


DEFAULT_SIGNATURES: dict[RelationshipType, RelationSignature] = {
    RelationshipType.HAS_INDUSTRY: _sig(
        (EntityType.COUNTY,), (EntityType.INDUSTRY,), "县域拥有/主导产业"
    ),
    RelationshipType.CONTAINS: _sig(
        (EntityType.INDUSTRY, EntityType.INDUSTRY_SEGMENT, EntityType.INDUSTRIAL_PARK),
        (EntityType.INDUSTRY_SEGMENT, EntityType.ENTERPRISE),
        "产业包含环节 / 园区包含企业",
    ),
    RelationshipType.BELONGS_TO: _sig(
        (
            EntityType.INDUSTRY_SEGMENT,
            EntityType.ENTERPRISE,
            EntityType.PRODUCT,
            EntityType.PATENT,
        ),
        (EntityType.INDUSTRY, EntityType.INDUSTRY_SEGMENT, EntityType.TECHNOLOGY),
        "归属关系",
    ),
    RelationshipType.LOCATED_IN: _sig(
        (
            EntityType.ENTERPRISE,
            EntityType.INDUSTRIAL_PARK,
            EntityType.INSTITUTION,
            EntityType.PATENT,
        ),
        (EntityType.COUNTY,),
        "坐落于县域",
    ),
    RelationshipType.PRODUCES: _sig(
        (EntityType.ENTERPRISE, EntityType.INDUSTRY_SEGMENT),
        (EntityType.PRODUCT, EntityType.MATERIAL),
        "生产产品/材料",
    ),
    RelationshipType.USES_INPUT: _sig(
        (EntityType.ENTERPRISE, EntityType.INDUSTRY_SEGMENT, EntityType.PRODUCT),
        (EntityType.MATERIAL, EntityType.PRODUCT, EntityType.TECHNOLOGY),
        "投入品/技术依赖",
    ),
    RelationshipType.SUPPLIES_TO: _sig(
        (EntityType.ENTERPRISE, EntityType.INDUSTRY_SEGMENT),
        (EntityType.ENTERPRISE, EntityType.INDUSTRY_SEGMENT),
        "上下游供应",
    ),
    RelationshipType.COOPERATES_WITH: _sig(
        (EntityType.ENTERPRISE, EntityType.INSTITUTION, EntityType.COUNTY),
        (EntityType.ENTERPRISE, EntityType.INSTITUTION, EntityType.COUNTY),
        "合作",
    ),
    RelationshipType.COMPETES_WITH: _sig(
        (EntityType.ENTERPRISE,), (EntityType.ENTERPRISE,), "竞争"
    ),
    RelationshipType.SUPPORTS: _sig(
        (EntityType.POLICY, EntityType.INSTITUTION, EntityType.COUNTY),
        (EntityType.INDUSTRY, EntityType.INDUSTRY_SEGMENT, EntityType.ENTERPRISE),
        "政策/机构支持产业或企业",
    ),
    RelationshipType.DEVELOPS: _sig(
        (EntityType.ENTERPRISE, EntityType.INSTITUTION),
        (EntityType.TECHNOLOGY, EntityType.PATENT, EntityType.PRODUCT),
        "研发技术/专利/产品",
    ),
    RelationshipType.APPLIED_IN: _sig(
        (EntityType.TECHNOLOGY, EntityType.PATENT),
        (EntityType.INDUSTRY, EntityType.INDUSTRY_SEGMENT, EntityType.PRODUCT),
        "技术应用于产业/产品",
    ),
    RelationshipType.OWNS: _sig(
        (EntityType.ENTERPRISE, EntityType.INSTITUTION),
        (EntityType.PATENT, EntityType.TECHNOLOGY),
        "拥有专利/技术",
    ),
}


@dataclass
class OntologySchema:
    """本体校验器。

    校验失败默认返回 warning 而不是直接拒绝，便于抽取阶段先记录后人工复核；
    ``strict=True`` 时非法签名会抛 ``ValueError``。
    """

    signatures: dict[RelationshipType, RelationSignature] = field(
        default_factory=lambda: dict(DEFAULT_SIGNATURES)
    )
    strict: bool = False

    def validate_relation(
        self,
        relation: KGRelation,
        source_entity: KGEntity | None,
        target_entity: KGEntity | None,
    ) -> list[str]:
        warnings: list[str] = []
        signature = self.signatures.get(relation.relationship_type)
        if signature is None:
            warnings.append(f"未注册的关系类型: {relation.relationship_type.value}")
        else:
            if source_entity is not None and source_entity.type not in signature.sources:
                warnings.append(
                    f"{source_entity.type.value} 不应作为 "
                    f"{relation.relationship_type.value} 的起点"
                )
            if target_entity is not None and target_entity.type not in signature.targets:
                warnings.append(
                    f"{target_entity.type.value} 不应作为 "
                    f"{relation.relationship_type.value} 的终点"
                )
        if self.strict and warnings:
            raise ValueError("; ".join(warnings))
        return warnings

    def allowed_relation_names(self) -> list[str]:
        return [rel.value for rel in self.signatures]


def default_schema(strict: bool = False) -> OntologySchema:
    return OntologySchema(strict=strict)


__all__ = [
    "DEFAULT_SIGNATURES",
    "OntologySchema",
    "RelationSignature",
    "default_schema",
]
