"""Conservative offline adapter: explicit annual bamboo output and reported growth.

Only verbatim lexical matches are emitted. Other indicators remain missing.
No answer files or historical generated reports are consulted.
"""
import re

RULE = 'bamboo_explicit_annual_v1: 年份＋全县竹产业总产值＋金额；紧邻同比为来源报告增速'
PATTERN = re.compile(
    r'(?P<year>20\d{2})年全县竹产业总产值(?P<verb>达到|约|达)?'
    r'(?P<value>\d+(?:\.\d+)?)亿元[，,]同比增长(?P<approx>约)?'
    r'(?P<growth>\d+(?:\.\d+)?)%')


def bamboo_candidates(content, region_id):
    facts = []
    for m in PATTERN.finditer(content):
        for metric, name, value, unit in (
            ('bamboo_output', '竹产业总产值', m['value'], '亿元'),
            ('bamboo_reported_growth', '竹产业总产值同比增长', m['growth'], '%'),
        ):
            facts.append(dict(region_id=region_id, metric_id=metric, original_name=name,
                              value=value, unit=unit, period=m['year'], scope='county',
                              caliber='unknown', price_basis='unknown',
                              qualifier='approximate' if m['verb'] == '约' or m['approx']
                              else 'unknown', excerpt=m.group(), start=m.start(),
                              mapping_basis=RULE, extraction_status='rule_candidate'))
    return facts
