"""多智能体深度研究系统。"""
from .coordinator import DeepResearchCoordinator, DeepResearchResult
from .critic import ResearchCritic
from .specialized import (
    EconomicAnalysisOutput,
    EconomicResearchAgent,
    IndustryAnalysisOutput,
    IndustryResearchAgent,
    PolicyAnalysisOutput,
    PolicyResearchAgent,
    ResearchSynthesizer,
)
from .tree import build_question_tree

__all__ = [
    "DeepResearchCoordinator",
    "DeepResearchResult",
    "EconomicAnalysisOutput",
    "EconomicResearchAgent",
    "IndustryAnalysisOutput",
    "IndustryResearchAgent",
    "PolicyAnalysisOutput",
    "PolicyResearchAgent",
    "ResearchCritic",
    "ResearchSynthesizer",
    "build_question_tree",
]
