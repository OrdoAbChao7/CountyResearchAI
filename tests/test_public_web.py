from __future__ import annotations

import hashlib
import json

from county_research_ai.search.public_web import (
    FreeWebClient,
    page_text,
    parse_ddg_results,
)

DDG_HTML = """
<html><body>
<div class="result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.gov.cn%2Fa">德清统计</a>
  <a class="result__snippet">2024年德清县GDP 722.5亿元</a>
</div>
<div class="result">
  <a class="result__a" href="https://example.gov.cn/a">重复</a>
</div>
<div class="result">
  <a class="result__a" href="https://example.gov.cn/b">第二来源</a>
</div>
</body></html>
"""


def test_parse_ddg_results_decodes_and_dedupes():
    results = parse_ddg_results(DDG_HTML)

    assert [result.url for result in results] == [
        "https://example.gov.cn/a",
        "https://example.gov.cn/b",
    ]
    assert results[0].title == "德清统计"
    assert "722.5" in results[0].snippet


def test_page_text_strips_scripts_and_title():
    title, text = page_text(
        "<html><head><title>公报</title><script>bad()</script></head>"
        "<body><p>第一产业增加值31.4亿元</p></body></html>"
    )

    assert title == "公报"
    assert "第一产业增加值31.4亿元" in text
    assert "bad()" not in text


def test_search_cache_hit_makes_no_request(tmp_path):
    query = "德清县 2006 工业总产值"
    key = hashlib.sha256(query.encode("utf-8")).hexdigest()
    cache_dir = tmp_path / "search"
    cache_dir.mkdir(parents=True)
    (cache_dir / f"{key}.json").write_text(
        json.dumps(
            [{"title": "缓存", "url": "https://cache.gov.cn/1", "snippet": "x"}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    client = FreeWebClient(tmp_path)

    results = client.search(query, max_results=5)

    assert results[0].url == "https://cache.gov.cn/1"
    assert client.request_count == 0


def test_decode_html_prefers_gbk_content_over_wrong_header():
    from county_research_ai.search.public_web import decode_html

    html = (
        "<html><head><title>2006年统计公报</title></head>"
        "<body>工业总产值达513.6亿元</body></html>"
    ).encode("gb18030")

    decoded = decode_html(html, "utf-8")

    assert "工业总产值达513.6亿元" in decoded
    assert "2006年统计公报" in decoded


def test_decode_html_prefers_valid_utf8_over_legacy_charset():
    from county_research_ai.search.public_web import decode_html

    html = "<html><title>后工业时代的乡村突围</title><body>二产比重59.1%</body></html>".encode()

    decoded = decode_html(html, "gb18030")

    assert "后工业时代的乡村突围" in decoded
    assert "二产比重59.1%" in decoded
