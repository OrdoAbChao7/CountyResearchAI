from county_research_ai import models
from county_research_ai.domain.common import CountyInfo
from county_research_ai.domain.long_history import HistoricalPeriod
from county_research_ai.domain.reports import ResearchReport


def test_domain_exports_preserve_legacy_model_identity() -> None:
    assert CountyInfo is models.CountyInfo
    assert HistoricalPeriod is models.HistoricalPeriod
    assert ResearchReport is models.ResearchReport
