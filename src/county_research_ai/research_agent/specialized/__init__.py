"""专业研究智能体角色与合成器。"""
from .economic import EconomicAnalysisOutput, EconomicResearchAgent
from .industry import IndustryAnalysisOutput, IndustryResearchAgent
from .policy import PolicyAnalysisOutput, PolicyResearchAgent
from .synthesizer import ResearchSynthesizer

__all__ = [
    "EconomicAnalysisOutput",
    "EconomicResearchAgent",
    "IndustryAnalysisOutput",
    "IndustryResearchAgent",
    "PolicyAnalysisOutput",
    "PolicyResearchAgent",
    "ResearchSynthesizer",
]
