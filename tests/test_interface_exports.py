from county_research_ai.cli import app as legacy_app
from county_research_ai.interfaces.cli import app


def test_cli_interface_preserves_public_app_identity() -> None:
    assert app is legacy_app
