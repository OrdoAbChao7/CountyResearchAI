import sys
missing = []

# 1. 基础层
try:
    from county_research_ai import __version__
    print(f'[OK] __init__ version={__version__}')
except Exception as e:
    print(f'[FAIL] __init__: {type(e).__name__}: {e}'); missing.append('__init__')

try:
    from county_research_ai.exceptions import CountyResearchAIError, ConfigError, SearchError
    e = ConfigError('test', context={'a':1})
    print(f'[OK] exceptions: str={e}')
except Exception as e:
    print(f'[FAIL] exceptions: {type(e).__name__}: {e}'); missing.append('exceptions')

try:
    from county_research_ai.models import (
        CountyInfo, RawDoc, ProcessedData, ResearchRequest, ResearchReport,
        AnalysisResult, ReportSection,
    )
    ci = CountyInfo.from_name('安吉县')
    print(f'[OK] models: county display={ci.display()}')
    r = ResearchRequest(county='安吉县', focus='竹产业')
    print(f'[OK] ResearchRequest: county={r.county}, focus={r.focus}')
    # 模型关系一致性:ProcessedData.render_for_llm 可运行
    doc = RawDoc(title='t', url='u', snippet='s', content='c'*100)
    pd = ProcessedData(county=ci, focus='竹产业', docs=[doc], total_chars=100)
    text = pd.render_for_llm(max_chars=50)
    print(f'[OK] ProcessedData.render_for_llm(50) len={len(text)}')
except Exception as e:
    import traceback; traceback.print_exc()
    print(f'[FAIL] models: {type(e).__name__}: {e}'); missing.append('models')

# 2. 三个 base.py
try:
    from county_research_ai.search.base import SearchProvider
    has_s = hasattr(SearchProvider, 'search')
    has_n = hasattr(SearchProvider, 'name')
    print(f'[OK] search.base: abstract search={has_s}, name={has_n}')
except Exception as e:
    print(f'[FAIL] search.base: {type(e).__name__}: {e}'); missing.append('search.base')

try:
    from county_research_ai.llm.base import LLMClient, LLMResponse
    print(f'[OK] llm.base: LLMResponse fields={sorted(LLMResponse.model_fields.keys())}')
except Exception as e:
    print(f'[FAIL] llm.base: {type(e).__name__}: {e}'); missing.append('llm.base')

try:
    from county_research_ai.storage.base import Storage
    need = ['save_raw','load_raw','save_processed','load_processed','save_report']
    missing_methods = [n for n in need if not hasattr(Storage, n)]
    print(f'[OK] storage.base: missing_methods={missing_methods}')
except Exception as e:
    print(f'[FAIL] storage.base: {type(e).__name__}: {e}'); missing.append('storage.base')

# 3. pipeline
try:
    from county_research_ai.pipeline import (
        ResearchPipeline, create_default_pipeline,
        MockSearchProvider, MockStorage, MockLLMClient,
    )
    pipe = create_default_pipeline()
    print(f'[OK] pipeline: create_default_pipeline OK')
    # Mock 各组件返回类型
    docs = pipe.search.search('安吉县 竹产业', max_results=2)
    print(f'[OK] MockSearch: docs count={len(docs)}, type={type(docs[0]).__name__}')
    resp = pipe.llm.complete('test')
    print(f'[OK] MockLLM complete len={len(resp)}')
except Exception as e:
    import traceback; traceback.print_exc()
    print(f'[FAIL] pipeline: {type(e).__name__}: {e}'); missing.append('pipeline')

print()
if missing:
    print(f'存在 {len(missing)} 个问题: {missing}')
    sys.exit(1)
else:
    print('基础层 + 接口层 + Pipeline 全部通过 ✅')
