from county_research_ai.application.context import ResearchContext
from county_research_ai.domain.modes import normalize_mode, normalize_request
from county_research_ai.models import ResearchRequest


def test_industry_alias_normalizes_without_mutating_request():
    request = ResearchRequest(county="安吉县", focus="竹产业", mode="industry")

    normalized = normalize_request(request)

    assert normalized.mode == "snapshot"
    assert request.mode == "industry"


def test_unknown_mode_is_rejected():
    try:
        normalize_mode("rise_fall_analysis")
    except ValueError as exc:
        assert "unsupported research mode" in str(exc)
    else:
        raise AssertionError("unknown mode was accepted")


def test_context_derives_county_from_normalized_request():
    context = ResearchContext.from_request(
        ResearchRequest(county="安吉县", mode="snapshot")
    )
    assert context.county.name == "安吉县"
    assert context.focus == ""
