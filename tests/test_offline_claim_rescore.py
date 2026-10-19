from __future__ import annotations

import json

from scripts.run_independent_judges import JudgeCandidate
from scripts.score_independent_claims_offline import source_material_for_offline_rescore

from county_research_ai.evaluation.judging import AnonymousReport
from county_research_ai.models import RawDoc


def test_offline_rescore_rebuilds_metadata_only_archive_from_saved_raw_docs(tmp_path):
    raw_dir = tmp_path / "data" / "raw" / "德清县" / "2024"
    raw_dir.mkdir(parents=True)
    document = RawDoc(
        title="2024年德清县统计公报",
        url="https://deqing.gov.cn/bulletin",
        content="2024年德清县生产总值722.5亿元。",
    )
    (raw_dir / "raw_docs.json").write_text(
        json.dumps([document.model_dump(mode="json")], ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "sources.json").write_text(
        json.dumps({"report_path": "report.md", "sections": []}),
        encoding="utf-8",
    )
    candidate = JudgeCandidate(
        run_id="run-1",
        group="C",
        county="德清县",
        task_id="snapshot",
        run_dir=tmp_path,
        anonymous_report=AnonymousReport(text="报告", report_hash="hash"),
    )

    source_material, status = source_material_for_offline_rescore(candidate)

    assert status == "rebuilt_from_saved_raw_docs"
    assert "722.5亿元" in source_material
    assert "content_hash" in source_material
