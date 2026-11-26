"""Contract questions steer retrieval and need their own verified answers."""
from __future__ import annotations

from collections import Counter

import pytest
from fastapi.testclient import TestClient

from county_research_ai.api.app import create_app
from county_research_ai.api.jobs import JobStatus
from county_research_ai.domain.outcomes import ResearchOutcome
from county_research_ai.mocks.search import MockSearchProvider
from county_research_ai.models import RawDoc
from tests.test_api_app import _wait_for_terminal

TOTAL_QUESTION = "2024 年安吉县竹产业总产值是多少？"
ENTERPRISE_QUESTION = "安吉县有哪些竹产业龙头企业？"


def _document(path: str, content: str) -> RawDoc:
    return RawDoc(
        title=f"安吉县竹产业资料 {path}",
        url=f"https://example.gov.cn/anji/{path}",
        content=content,
        source="fixture",
    )


@pytest.mark.parametrize(
    ("with_answers", "with_quarterly_value", "expected_outcome"),
    [
        (False, True, "NEEDS_HUMAN_REVIEW"),
        (True, False, "SUFFICIENT"),
        (True, True, "SUFFICIENT"),
    ],
    ids=["gaps", "direct-evidence", "quarterly-context"],
)
def test_required_questions_drive_search_and_report(
    tmp_path, tmp_settings_no_key, monkeypatch, with_answers, with_quarterly_value, expected_outcome,
):
    county_report = _document(
        "statistics",
        "2024年安吉县地区生产总值为600亿元。2024年安吉县建筑业总产值为135.33亿元。"
        "2024年安吉县规上绿色竹业增加值为6.90亿元。2023年安吉县竹产业总产值为180.28亿元。"
        "2024年安吉县竹产业园内有例木有限公司参与生产。建议由国资公司出资控股、龙头企业参与运营。",
    )
    mixed_periods = _document(
        "business-profile",
        "2024年安吉县地区生产总值为608亿元。安吉县例旧有限公司为竹产业龙头企业。"
        "这里同时介绍企业历年沿革与县情统计。"
        + ("2024年第一季度，按统一口径核算，安吉县竹产业总产值达到55亿元。" if with_quarterly_value else ""),
    )
    industry_output = _document(
        "industry-output",
        "2024年安吉县竹产业总产值达到280亿元。全县各园区同步公开年度统计。"
        "本次统计范围包括竹资源培育及相关加工服务。",
    )
    enterprise_designation = _document(
        "designations",
        "2024年安吉县例竹有限公司获认定为竹产业龙头企业。该认定已依法公示。"
        "公示材料附有企业的完整登记名称与经营地址。",
    )
    queries: list[str] = []

    def search(self, query: str, max_results: int = 10) -> list[RawDoc]:
        queries.append(query)
        if with_answers and "总产值" in query and "年度统计" in query:
            return [industry_output]
        if with_answers and "龙头企业" in query and "认定" in query:
            return [enterprise_designation]
        return [county_report, mixed_periods]

    monkeypatch.setattr(MockSearchProvider, "search", search)
    app = create_app(
        settings=tmp_settings_no_key,
        live_enabled=False,
        data_dir=tmp_path / "data",
        reports_dir=tmp_path / "reports",
        evidence_db_path=tmp_path / "evidence.sqlite",
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/research/tasks",
            json={"contract": {
                "objective": "核验 2024 年竹产业总产值与龙头企业",
                "regions": ["安吉县"],
                "research_focus": "竹产业",
                "date_window": {"start": "2024-01-01", "end": "2024-12-31"},
                "required_questions": [TOTAL_QUESTION, ENTERPRISE_QUESTION],
                "options": {"deep_research": True},
            }},
        )
        assert response.status_code == 202, response.text
        job_id = response.json()["job_id"]
        detail = _wait_for_terminal(client, job_id)
        report_response = client.get(f"/api/v1/research/tasks/{job_id}/report.json")

    assert detail["status"] == "SUCCEEDED", detail
    assert any("安吉县" in q and "2024" in q and "竹产业总产值" in q for q in queries), queries
    assert any("安吉县" in q and "2024" in q and "竹产业龙头企业" in q for q in queries), queries
    assert any("总产值" in q and "年度统计" in q for q in queries), queries
    assert any("龙头企业" in q and "认定" in q for q in queries), queries
    assert max(Counter(queries).values()) == 1
    assert report_response.status_code == 200, report_response.text
    report = report_response.json()
    questions = report["contract_questions"]
    assert [(item["question_id"], item["question"]) for item in questions] == [
        ("contract:0", TOTAL_QUESTION), ("contract:1", ENTERPRISE_QUESTION)
    ]
    question_gaps = {
        gap["question_id"] for gap in report["gaps"] if gap["question_id"].startswith("contract:")
    }
    assert detail["outcome"] == expected_outcome, detail["result"]["evidence"]
    assert detail["result"]["evidence"]["status_counts"]["NEEDS_REVIEW"] >= 2
    if with_answers:
        assert [item["status"] for item in questions] == ["SUPPORTED", "SUPPORTED"]
        assert not question_gaps
        if with_quarterly_value:
            quarterly, = [item for item in questions[0]["candidates"] if "55亿元" in item["statement"]]
            assert quarterly["status"] == "REJECTED"
            assert quarterly["claim_id"] not in questions[0]["claim_ids"]
            assert all(quarterly["claim_id"] not in conflict["conflicting_claim_ids"] for conflict in report["claim_conflicts"])
            assert all(
                member["value"] != "55亿元"
                for conflict in report["conflicts"] if conflict["conflict_type"] == "contradiction"
                for member in conflict["claims"]
            )
        by_claim = {item["claim_id"]: item for item in report["citations"]}
        for question, token in zip(questions, ("280亿元", "例竹有限公司"), strict=True):
            answers = [by_claim[claim_id] for claim_id in question["claim_ids"]]
            assert answers
            assert all(token in answer["quote"] for answer in answers)
    else:
        assert detail["outcome_reason"] == "required_questions_unanswered"
        assert {item["status"] for item in questions} == {"INSUFFICIENT"}
        assert all(not item["claim_ids"] for item in questions)
        assert question_gaps == {"contract:0", "contract:1"}
        totals = questions[0]["candidates"]
        previous_year, = [item for item in totals if "180.28亿元" in item["statement"]]
        related_metric, = [item for item in totals if "6.90亿元" in item["statement"]]
        assert previous_year["reason"] == "outside_requested_period"
        assert related_metric["reason"] == "different_metric_or_qualification"
        assert related_metric["status"] == "REJECTED" and related_metric["span_id"]


@pytest.fixture
def contract_client(tmp_path, tmp_settings_no_key):
    app = create_app(
        settings=tmp_settings_no_key,
        live_enabled=False,
        data_dir=tmp_path / "data",
        reports_dir=tmp_path / "reports",
        evidence_db_path=tmp_path / "evidence.sqlite",
    )
    with TestClient(app) as client:
        yield client


def _run_contract(
    client, questions, *, region="安吉县", window=None, deep_research=False,
):
    response = client.post("/api/v1/research/tasks", json={"contract": {
        "objective": "核验县域产业年度数据",
        "regions": [region],
        "research_focus": "竹产业",
        "date_window": window or {"start": "2024-01-01", "end": "2024-12-31"},
        "required_questions": questions,
        "options": {"deep_research": deep_research},
    }})
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    detail = _wait_for_terminal(client, job_id)
    assert detail["status"] == "SUCCEEDED", detail
    report = client.get(f"/api/v1/research/tasks/{job_id}/report.json")
    assert report.status_code == 200, report.text
    return detail, report.json()


def test_low_credibility_total_is_a_locatable_candidate(contract_client, monkeypatch):
    paragraph = "安吉县竹林面积达100万亩，占全国竹资源重要地位，2024年竹产业总产值达192亿元。"
    secondary = RawDoc(
        title="小蜂观察：浙江省安吉县竹产业转型路径与百亿绿色经济的启示-农小蜂",
        url="https://example.com/bamboo-observation",
        content=paragraph + "该文介绍当地竹产业发展历程，涵盖竹林经营、原竹加工、竹制品出口和产业园建设。",
        credibility_score=0.5,
    )
    bulletin = _document(
        "annual-statistics",
        "2024年安吉县建筑业总产值达135.33亿元。全县年度统计已公开。"
        "县级统计公报汇总了各部门的生产经营数据，详细分列建筑业、服务业和其他行业。",
    )
    monkeypatch.setattr(MockSearchProvider, "search", lambda self, query, max_results=10: [secondary, bulletin])

    detail, report = _run_contract(contract_client, [TOTAL_QUESTION, ENTERPRISE_QUESTION], deep_research=True)

    question = report["contract_questions"][0]
    assert question["question"] == TOTAL_QUESTION
    assert (question["status"], question["claim_ids"]) == ("INSUFFICIENT", [])
    assert detail["outcome"] == "NEEDS_HUMAN_REVIEW"
    candidate, = [item for item in question["candidates"] if "192亿元" in item["statement"]]
    claim_id = candidate["claim_id"]
    assert candidate["reason"] == "insufficient_source_credibility"
    assert candidate["status"] == "REJECTED" and candidate["span_id"] and candidate["snapshot_id"]
    assert "待核验" in report["markdown"]
    citation, = [item for item in report["citations"] if item["claim_id"] == claim_id]
    assert citation["status"] == "INSUFFICIENT"
    assert citation["span_id"] == candidate["span_id"] and paragraph in citation["quote"]
    facts = next(section for section in report["sections"] if section["id"] == "verified-facts")
    assert claim_id not in facts["citation_ids"]
    assert not report["conflicts"] and not report["claim_conflicts"]

    url = f"/api/v1/research/tasks/{detail['job_id']}"
    claim_response = contract_client.get(f"{url}/claims/{claim_id}")
    assert claim_response.status_code == 200, claim_response.text
    finding = claim_response.json()["finding"]
    assert finding["status"] == "INSUFFICIENT"
    assert finding["claim"]["region"] == "安吉县" and finding["claim"]["scope"] == "县域本级"
    assert finding["claim"]["verification_reason"] == candidate["reason"]
    graph = contract_client.get(f"{url}/graph").json()
    node_id = f"ev:{claim_id}"
    node = next(node for node in graph["nodes"] if node["id"] == node_id)
    assert node["data"]["status"] == "INSUFFICIENT"
    assert any(edge["type"] == "cited_from" and edge["source"] == node_id for edge in graph["edges"])
    assert not any(edge["type"] == "supported_by" and edge["target"] == node_id for edge in graph["edges"])


@pytest.mark.parametrize(("second_amount", "expected"), [
    ("200亿元", "CONFLICT_UNRESOLVED"),
    ("2800000万元", "SUPPORTED"),
], ids=["different-amounts", "equivalent-units"])
def test_annual_answers_compare_amounts_across_predicates(contract_client, monkeypatch, second_amount, expected):
    documents = [
        _document("annual-statistics", "2024年安吉县竹产业总产值为280亿元。年度统计涵盖原竹生产及加工。全县产业园区同时公开了相关资料。"),
        _document("annual-accounting", f"2024年安吉县竹产业总产值达到{second_amount}。数据来自县域年度产业核算。上游只计算纳入统计的生产活动。"),
    ]
    monkeypatch.setattr(MockSearchProvider, "search", lambda self, query, max_results=10: documents)

    detail, report = _run_contract(contract_client, [TOTAL_QUESTION], deep_research=True)

    question, = report["contract_questions"]
    assert question["status"] == expected
    assert detail["outcome"] == ("SUFFICIENT" if expected == "SUPPORTED" else expected)
    assert len(question["claim_ids"]) == 2
    facts = next(section for section in report["sections"] if section["id"] == "verified-facts")
    url = f"/api/v1/research/tasks/{detail['job_id']}"
    if expected == "CONFLICT_UNRESOLVED":
        assert not set(question["claim_ids"]) & set(facts["citation_ids"])
        assert {item["claim_id"] for item in report["claim_conflicts"]} == set(question["claim_ids"])
        evidence = contract_client.get(f"{url}/evidence").json()["items"]
        graph = contract_client.get(f"{url}/graph").json()
        claims = contract_client.get(f"{url}/claims").json()
        assert {item["status"] for item in evidence} == {"NEEDS_REVIEW"}
        assert {item["finding"]["status"] for item in claims} == {"NEEDS_REVIEW"}
        assert {node["data"]["status"] for node in graph["nodes"] if node["type"] == "evidence"} == {"NEEDS_REVIEW"}
        brief = contract_client.get(f"{url}/brief").text
        assert "冲突待复核" in brief and "## 已支持结论" not in brief
    else:
        assert set(question["claim_ids"]) == set(facts["citation_ids"])


def test_nearly_identical_documents_retain_both_annual_amounts(contract_client, monkeypatch):
    text = (
        "2024年安吉县竹产业总产值为120亿元。全县各园区同步公开年度统计，数据覆盖生产和加工。"
        "县域产业年度核算资料已在门户网站公开发布。"
    )
    documents = [
        RawDoc(title=f"安吉县竹产业年度统计通报第{index}期", url=f"https://example.gov.cn/anji/report-{index}",
               content=text.replace("120亿元", amount), source="fixture")
        for index, amount in [(1, "120亿元"), (2, "125亿元")]
    ]
    monkeypatch.setattr(MockSearchProvider, "search", lambda self, query, max_results=10: documents)

    detail, report = _run_contract(contract_client, [TOTAL_QUESTION])

    question, = report["contract_questions"]
    assert detail["outcome"] == question["status"] == "CONFLICT_UNRESOLVED"
    assert len(question["claim_ids"]) == 2
    assert {citation["value"] for citation in report["citations"]} == {"120", "125"}


@pytest.mark.parametrize("changed_field", ["content", "title"])
def test_contract_citations_only_use_current_run_snapshots(contract_client, monkeypatch, changed_field):
    statement = "2024年安吉县竹产业总产值为280亿元。"
    description = "公报汇总全县相关生产数据。各产业园区公布了本次统计所用材料。"
    document = _document("annual", statement + description)
    documents = [document]
    monkeypatch.setattr(MockSearchProvider, "search", lambda self, query, max_results=10: documents)
    first, _ = _run_contract(contract_client, [TOTAL_QUESTION])
    assert first["outcome"] == "SUFFICIENT"
    documents[:] = [document.model_copy(update={changed_field: "预测：" + getattr(document, changed_field)})]

    detail, report = _run_contract(contract_client, [TOTAL_QUESTION])

    question, = report["contract_questions"]
    assert question["status"] == "INSUFFICIENT" and not question["claim_ids"]
    assert detail["outcome"] == "NEEDS_HUMAN_REVIEW"
    revised_citations = [citation for citation in report["citations"] if "280亿元" in citation["quote"]]
    assert revised_citations
    assert all("预测" in f"{citation['title']} {citation['quote']}" for citation in revised_citations)


def test_annual_report_keeps_its_version_after_a_title_only_year_change(contract_client, monkeypatch):
    document = _document(
        "bulletin", "初步核算，全年地区生产总值为660.07亿元。全县各主要部门汇总报送了经济运行数据。"
        "该统计公报已在县级门户网站公布。",
    )
    documents = [document.model_copy(update={"title": "2024年安吉县国民经济和社会发展统计公报"})]
    monkeypatch.setattr(MockSearchProvider, "search", lambda self, query, max_results=10: list(documents))
    first, first_report = _run_contract(contract_client, ["2024年安吉县地区生产总值是多少？"])
    documents[:] = [document.model_copy(update={"title": "2023年安吉县国民经济和社会发展统计公报"})]

    second, second_report = _run_contract(
        contract_client, ["2023年安吉县地区生产总值是多少？"],
        window={"start": "2023-01-01", "end": "2023-12-31"},
    )

    assert first["outcome"] == second["outcome"] == "SUFFICIENT"
    prior, = first_report["citations"]
    later, = second_report["citations"]
    assert prior["claim_id"] == later["claim_id"]
    assert (prior["period"], later["period"]) == ("2024", "2023")
    assert prior["snapshot_id"] != later["snapshot_id"]
    earlier_again = contract_client.get(f"/api/v1/research/tasks/{first['job_id']}/report.json").json()
    assert earlier_again["citations"] == [prior]
    assert earlier_again["contract_questions"] == first_report["contract_questions"]


@pytest.mark.parametrize(("question", "title", "content", "expected"), [
    (
        TOTAL_QUESTION,
        "安吉县竹产业年度统计",
        "按规模以上企业口径统计，2024年安吉县竹产业总产值为280亿元。",
        "INSUFFICIENT",
    ),
    (
        ENTERPRISE_QUESTION,
        "安吉县2024年竹产业龙头企业拟入选名单",
        "2024年安吉县例竹有限公司为竹产业龙头企业。",
        "INSUFFICIENT",
    ),
    (
        ENTERPRISE_QUESTION,
        "2024年安吉县竹产业龙头企业候选名单",
        "2024年安吉县例竹有限公司为竹产业龙头企业。",
        "INSUFFICIENT",
    ),
    (
        TOTAL_QUESTION,
        "安吉县竹产业年度统计",
        "本次仅统计规模以上企业。2024年安吉县竹产业总产值为120亿元。",
        "INSUFFICIENT",
    ),
    (
        TOTAL_QUESTION,
        "安吉县竹产业年度统计",
        "2024年安吉县规上绿色竹业增加值为6.90亿元。2024年安吉县竹产业总产值为120亿元。",
        "SUPPORTED",
    ),
    (
        "2024年安吉县地区生产总值是多少？",
        "2024年安吉县国民经济和社会发展统计公报",
        "初步核算，全年地区生产总值为660.07亿元。",
        "SUPPORTED",
    ),
    (
        TOTAL_QUESTION,
        "安吉县竹产业年度统计",
        "2024年安吉县竹产业总产值为192亿元（约占全国竹产业总产值320亿元的60%）。",
        "SUPPORTED",
    ),
    (
        TOTAL_QUESTION,
        "安吉县竹产业年度统计",
        "2024年安吉县竹产业总产值为192亿元（该数据有误，应为182亿元）。",
        "INSUFFICIENT",
    ),
], ids=["subset-output", "provisional-list", "candidate-list", "declared-scope", "separate-statistic", "bulletin-year", "comparison-note", "corrected-amount"])
def test_direct_answers_respect_source_scope_and_reporting_year(
    contract_client, monkeypatch, question, title, content, expected,
):
    document = RawDoc(
        title=title, url="https://example.gov.cn/anji/local-statistics",
        content=content + "安吉县产业数据由各园区汇总报送。统计材料在县级网站发布供社会查阅。",
        source="fixture",
    )
    monkeypatch.setattr(MockSearchProvider, "search", lambda self, query, max_results=10: [document])

    _, report = _run_contract(contract_client, [question])

    result, = report["contract_questions"]
    assert result["status"] == expected
    assert bool(result["claim_ids"]) == (expected == "SUPPORTED")
    if expected == "INSUFFICIENT":
        assert report["verification"]["verified"] == 0


@pytest.mark.parametrize(("title", "expected"), [
    ("河北省石家庄市长安区2024年国民经济和社会发展统计公报", "INSUFFICIENT"),
    ("陕西省西安市长安区2024年国民经济和社会发展统计公报", "SUPPORTED"),
    ("2024年长安区统计公报（河北省石家庄市）", "INSUFFICIENT"),
    ("2024年长安区统计公报（陕西省西安市）", "SUPPORTED"),
])
def test_contract_queries_and_answers_keep_qualified_region(contract_client, monkeypatch, title, expected):
    document = RawDoc(
        title=title,
        url="https://example.gov.cn/statistics",
        content="2024年长安区地区生产总值为280亿元。全区公布年度产业发展统计资料。公报数据来自各主要部门的统计年报。",
        source="fixture",
    )
    queries = []

    def search(self, query, max_results=10):
        queries.append(query)
        return [document]

    monkeypatch.setattr(MockSearchProvider, "search", search)
    _, report = _run_contract(contract_client, ["2024年长安区地区生产总值是多少？"], region="陕西省西安市长安区")

    result, = report["contract_questions"]
    assert result["status"] == expected
    assert queries and all("陕西省" in query and "西安市" in query for query in queries)


def test_open_ended_window_retrieves_a_later_annual_answer(contract_client, monkeypatch):
    early = _document("historical", "2020年安吉县地区生产总值为610亿元。年度统计显示产业发展平稳，县域多家工业园区完成建设。")
    answer = _document(
        "recent", "2024年安吉县竹产业总产值为280亿元。县域统一汇总了各产业园区提交的生产和销售统计资料。"
        "这份年度核算覆盖全县竹产业的主要环节。",
    )
    queries = []

    def search(self, query, max_results=10):
        queries.append(query)
        return [early, answer]

    monkeypatch.setattr(MockSearchProvider, "search", search)
    detail, report = _run_contract(contract_client, [TOTAL_QUESTION], window={"start": "2020-01-01"}, deep_research=True)

    assert report["contract_questions"][0]["status"] == "SUPPORTED"
    assert detail["result"]["deep_research"]["retrieval_stop_reason"] == "quality_met"
    assert all("2024年" in query and "2020年" not in query for query in queries), queries


def test_snapshot_searches_every_required_question(contract_client, monkeypatch):
    questions = [f"请说明安吉县产业材料中第 {index} 项的公开依据" for index in range(1, 12)]
    queries = []

    def search(self, query, max_results=10):
        queries.append(query)
        return []

    monkeypatch.setattr(MockSearchProvider, "search", search)
    _, report = _run_contract(contract_client, questions)

    assert all(any(question in query for query in queries) for question in questions)
    assert len(report["contract_questions"]) == len(questions)


def test_multi_region_contract_is_rejected_before_scheduling(contract_client):
    response = contract_client.post("/api/v1/research/tasks", json={"contract": {
        "objective": "核验各县产业年度产值", "regions": ["安吉县", "德清县"],
        "required_questions": [TOTAL_QUESTION, "2024年德清县竹产业总产值是多少？"],
    }})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_multi_region"
    assert contract_client.get("/api/v1/research/tasks").json() == []


def test_claim_list_and_detail_expose_the_same_verified_chain(contract_client, monkeypatch):
    document = _document(
        "annual", "2024年安吉县竹产业总产值为280亿元。年度产值统计涵盖全县的产业活动。县级门户网站发布了这项统计结果。",
    )
    monkeypatch.setattr(MockSearchProvider, "search", lambda self, query, max_results=10: [document])
    detail, report = _run_contract(contract_client, ["2024年安吉县竹产业总产值为多少亿元？"])
    question, = report["contract_questions"]
    prefix = f"/api/v1/research/tasks/{detail['job_id']}"

    response = contract_client.get(f"{prefix}/claims")

    assert response.status_code == 200
    chain, = response.json()
    claim_id = chain["finding"]["claim"]["claim_id"]
    assert chain == contract_client.get(f"{prefix}/claims/{claim_id}").json()
    assert chain["finding"]["status"] == "SUPPORTED"
    assert question["status"] == "SUPPORTED"
    assert question["claim_ids"] == [claim_id]
    questions = contract_client.get(f"{prefix}/questions")
    assert questions.status_code == 200
    assert questions.json()["contract_questions"] == [question]
    assert questions.json()["questions"] == []


def test_question_views_trace_rejected_material_and_actual_followup(contract_client, monkeypatch):
    candidate = _document(
        "candidate", "2024年安吉县例竹有限公司为竹产业龙头企业。公示材料附企业名称和经营地址。"
        "所在园区定期公开县域竹产业经营统计。",
    ).model_copy(update={"title": "2024年安吉县竹产业龙头企业候选名单"})
    queries = []

    def search(self, query, max_results=10):
        queries.append(query)
        return [] if "认定公布" in query else [candidate]

    monkeypatch.setattr(MockSearchProvider, "search", search)
    detail, report = _run_contract(contract_client, [ENTERPRISE_QUESTION], deep_research=True)
    question, = report["contract_questions"]
    prefix = f"/api/v1/research/tasks/{detail['job_id']}"

    assert question["status"] == "INSUFFICIENT"
    assert question["missing_metrics"] == ["竹产业龙头企业"]
    material, = question["candidates"]
    assert material["reason"] == "provisional_or_nonfactual"
    assert material["url"] == candidate.url
    assert material["snapshot_id"] and material["span_id"]
    traces = question["query_executions"]
    assert {entry["query"] for entry in traces if entry["request"] == "executed"} == set(queries)
    followup, = [entry for entry in traces if entry["round"] == 2]
    assert followup["request"] == "executed" and followup["status"] == "empty"
    response = contract_client.get(f"{prefix}/questions")
    assert response.status_code == 200
    assert response.json()["contract_questions"] == [question]
    assert response.json()["questions"]
    brief = contract_client.get(f"{prefix}/brief")
    assert brief.status_code == 200
    assert "## 已支持结论" not in brief.text
    for markdown in (brief.text, report["markdown"]):
        assert ENTERPRISE_QUESTION in markdown
        assert material["title"] in markdown and material["span_id"] in markdown
        assert "候选或非事实陈述" in markdown
        assert followup["query"] in markdown and "返回 0 份" in markdown
    assert any(gap["question_id"] == "contract:0" for gap in report["gaps"])


def test_contract_tries_distinct_strategies_after_repeated_results(contract_client, monkeypatch):
    weak_total = _document(
        "weak-output",
        "2024年安吉县竹产业总产值为192亿元。文中还介绍了全县竹产业经营统计和加工园区的建设情况。"
        "文章讨论竹林培育、原竹运输及竹制品加工的产业协作。"
    ).model_copy(update={"url": "https://example.com/observation"})
    official_output = _document(
        "industry-statistics",
        "2024年安吉县竹产业总产值为280亿元。专项统计报告包含县内生产服务和加工经营的年度统计。"
        "附表列出统计范围与资料填报口径。",
    )
    effective_designation = _document(
        "recognized-enterprises",
        "2024年安吉县例竹有限公司获认定为竹产业龙头企业。主管部门已公布有效名单和企业登记地址。"
        "附表提供登记事项和公开查询方式。",
    )

    def search(self, query, max_results=10):
        if "专项统计报告" in query:
            return [official_output]
        if "有效名单" in query:
            return [effective_designation]
        return [weak_total]

    monkeypatch.setattr(MockSearchProvider, "search", search)
    detail, report = _run_contract(contract_client, [TOTAL_QUESTION, ENTERPRISE_QUESTION], deep_research=True)

    assert detail["outcome"] == "SUFFICIENT"
    assert [question["status"] for question in report["contract_questions"]] == ["SUPPORTED", "SUPPORTED"]
    executions = [question["query_executions"] for question in report["contract_questions"]]
    assert [[entry["round"] for entry in group] for group in executions] == [[1, 2, 3], [1, 2, 3]]
    texts = [entry["query"] for group in executions for entry in group if entry["request"] == "executed"]
    assert len(texts) == len(set(texts)) == 6
    assert all("安吉县" in text and "2024年" in text for text in texts)
    assert "统计公报" in executions[0][1]["query"]
    assert "认定公布" in executions[1][1]["query"]
    assert "公示" not in executions[1][1]["query"]
    deep = detail["result"]["deep_research"]
    assert deep["retrieval_stop_reason"] == "quality_met"
    _, repeated, last = deep["period_coverage_history"]
    assert repeated["evidence_progress"] == "no_new_documents"
    assert repeated["new_eligible_claim_count"] == 0
    assert last["evidence_progress"] == "contract_coverage_improved"
    assert last["new_eligible_claim_count"] == last["new_covered_slot_count"] == 2
    assert last["eligible_source_group_count"] == 2
    amounts = [citation for citation in report["citations"] if citation["value"] == "192"]
    assert amounts and all(citation["status"] == "INSUFFICIENT" for citation in amounts)


@pytest.mark.parametrize(
    ("second_round", "stop_reason", "progress", "new_documents", "new_claims"),
    [
        ("context", "strategy_exhausted", "no_new_claims", 1, 0),
        ("other-year", "strategy_exhausted", "new_claims_without_contract_coverage", 1, 1),
        ("empty", "search_source_no_results", "no_new_documents", 0, 0),
    ],
)
def test_contract_stop_reports_the_observed_evidence_delta(
    contract_client, monkeypatch, second_round, stop_reason, progress, new_documents, new_claims,
):
    initial = _document(
        "initial", "安吉县发布了竹产业加工园区介绍。资料描述了园区空间布局和竹资源深加工服务。"
        "材料还介绍了园区面向入驻企业的公共服务和仓储设施。",
    )
    followup = {
        "context": _document(
            "context", "安吉县开展竹产业调研。调研组走访了当地加工园区，了解竹材加工服务。"
            "走访记录还讨论了竹产品展示与集中运输的筹备工作。",
        ),
        "other-year": _document(
            "other-year", "2025年安吉县建筑业总产值为121亿元。资料由县域产业园区汇总报送。"
            "建设部门提供了年度核算材料供县域经济研究查阅。",
        ),
    }.get(second_round)

    def search(self, query, max_results=10):
        if followup is None or "专项统计报告" in query:
            return []
        return [followup] if "年度统计" in query else [initial]

    monkeypatch.setattr(MockSearchProvider, "search", search)
    detail, report = _run_contract(contract_client, [TOTAL_QUESTION], deep_research=True)

    deep = detail["result"]["deep_research"]
    assert deep["retrieval_stop_reason"] == stop_reason
    _, second, last = deep["period_coverage_history"]
    assert second["evidence_progress"] == progress
    assert second["new_document_count"] == second["new_source_group_count"] == new_documents
    assert second["new_claim_count"] == new_claims
    assert second["new_eligible_claim_count"] == second["new_covered_slot_count"] == 0
    assert last["stop_reason"] == stop_reason
    question, = report["contract_questions"]
    assert question["status"] == "INSUFFICIENT" and not question["claim_ids"]
    assert [entry["round"] for entry in question["query_executions"]] == [1, 2, 3]


def test_resume_records_only_its_own_query_executions(contract_client, monkeypatch):
    documents = []
    monkeypatch.setattr(MockSearchProvider, "search", lambda self, query, max_results=10: list(documents))
    previous, _ = _run_contract(contract_client, [TOTAL_QUESTION])
    job_id = previous["job_id"]
    old_trace = previous["result"]["evidence"]["contract_questions"][0]["query_executions"]
    assert len(old_trace) == 1 and old_trace[0]["status"] == "empty"
    contract_client.app.state.job_store.mark_terminal(
        job_id, JobStatus.INTERRUPTED, outcome=ResearchOutcome.FAILED, result=previous["result"],
    )
    documents.append(_document(
        "annual", "2024年安吉县竹产业总产值为280亿元。年度统计覆盖全县各产业园区。"
        "县级门户网站发布了这项年度统计结果。",
    ))
    prefix = f"/api/v1/research/tasks/{job_id}"

    resumed = contract_client.post(f"{prefix}/resume")
    assert resumed.status_code == 202
    finished = _wait_for_terminal(contract_client, job_id)

    assert finished["status"] == "SUCCEEDED", finished
    questions = contract_client.get(f"{prefix}/questions").json()["contract_questions"]
    question, = questions
    assert question["status"] == "SUPPORTED"
    current, = question["query_executions"]
    assert current["query"] == old_trace[0]["query"]
    assert (current["request"], current["status"], current["returned_documents"]) == ("executed", "results", 1)
    document, = current["documents"]
    assert document["url"] == "https://example.gov.cn/anji/annual"
    assert document["title"] == "安吉县竹产业资料 annual"
    assert (document["content_type"], document["text_origin"], document["parse_status"]) == ("", "content", "text")
    assert document["content_chars"] == len(
        "2024年安吉县竹产业总产值为280亿元。年度统计覆盖全县各产业园区。"
        "县级门户网站发布了这项年度统计结果。"
    )
    assert len(document["text_sha256"]) == 64


def test_mock_contract_uses_requested_county_for_fixtures(contract_client):
    detail, _ = _run_contract(contract_client, [TOTAL_QUESTION])

    assert detail["result"]["evidence"]["snapshots"] > 0
