from __future__ import annotations

import pytest

from county_research_ai.bootstrap.container import create_app_container
from county_research_ai.config import Settings
from county_research_ai.evaluation.strict_container import StrictRealContainer
from county_research_ai.exceptions import CountyResearchAIError, SearchError
from county_research_ai.mocks.llm import MockLLMClient
from county_research_ai.mocks.search import MockSearchProvider


def test_strict_container_does_not_fallback_when_credentials_are_missing():
    settings = Settings(llm={"api_key": ""}, search={"api_key": ""})

    with pytest.raises(CountyResearchAIError):
        StrictRealContainer.from_settings(settings)


def test_default_container_keeps_mock_fallback_for_offline_regression():
    settings = Settings(llm={"api_key": ""}, search={"api_key": ""})

    container = create_app_container(settings)

    assert isinstance(container.llm, MockLLMClient)
    assert hasattr(container.search, "provider")
    assert isinstance(container.search.provider, MockSearchProvider)


def test_fixed_input_container_disables_search_without_using_a_mock():
    settings = Settings(llm={"api_key": ""}, search={"api_key": ""})

    container = create_app_container(settings, search_enabled=False)

    assert container.search.name == "disabled-by-fixed-input-protocol"
    with pytest.raises(SearchError, match="E2 fixed-input protocol"):
        container.search.collect("新地区县", "特色产业", 1, mode="snapshot")


def test_strict_component_guard_rejects_mock_components():
    with pytest.raises(SearchError):
        StrictRealContainer.assert_no_mock(MockLLMClient(), MockSearchProvider())
