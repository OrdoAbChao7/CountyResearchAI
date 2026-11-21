"""产业知识图谱基础设施。

- ontology:        实体、关系与本体约束
- extraction:      LLM + 确定性规则抽取
- entity_resolution: 实体消歧与合并
- graph_store:     Neo4j / InMemory 图存储适配器
- graph_rag:       图谱检索与 GraphRAG 查询引擎
- temporal:        时序图谱数据模型与 as-of 查询
"""
from .ontology.entities import EntityType, KGEntity
from .ontology.relations import KGRelation, RelationshipType
from .ontology.schema import OntologySchema, default_schema

__all__ = [
    "EntityType",
    "KGEntity",
    "KGRelation",
    "OntologySchema",
    "RelationshipType",
    "default_schema",
]
