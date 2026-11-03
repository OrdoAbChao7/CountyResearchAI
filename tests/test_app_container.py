from __future__ import annotations

from county_research_ai.agent.tools import ResearchToolContext
from county_research_ai.application.research import ResearchApplication
from county_research_ai.bootstrap.container import AppContainer, create_app_container


def test_container_composes_shared_application_and_workflow(tmp_settings) -> None:
    container = create_app_container(tmp_settings)

    assert isinstance(container, AppContainer)
    assert isinstance(container.application, ResearchApplication)
    assert container.workflow.application is container.application
    assert isinstance(ResearchToolContext.from_pipeline(container.pipeline()).application, ResearchApplication)
