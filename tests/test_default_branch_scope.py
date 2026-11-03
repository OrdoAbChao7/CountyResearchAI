from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_default_branch_has_no_video_product_source():
    forbidden = [
        PROJECT_ROOT / "src/county_research_ai/content",
        PROJECT_ROOT / "src/county_research_ai/video",
        PROJECT_ROOT / "video_template",
        PROJECT_ROOT / "scripts/_verify_content.py",
    ]
    assert [str(path) for path in forbidden if path.exists()] == []
