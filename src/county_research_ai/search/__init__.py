"""数据采集层。

负责从多源采集县域产业相关数据:
    - web_search.py  通用网络搜索(Tavily/Serper/Bing)
    - gov_data.py    政府公开数据(统计局/工信部等白名单域名)
    - collector.py   协调器:并发调用多 provider,去重、限流、错误隔离
    - base.py        抽象接口 SearchProvider

所有采集结果输出 RawDoc 列表,落盘到 data/raw/。
"""
from __future__ import annotations
