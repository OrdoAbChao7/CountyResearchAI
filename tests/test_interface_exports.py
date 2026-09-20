from county_research_ai.cli import main as legacy_main
from county_research_ai.interfaces.cli import main


def test_cli_interface_preserves_public_app_identity() -> None:
    assert main is legacy_main
