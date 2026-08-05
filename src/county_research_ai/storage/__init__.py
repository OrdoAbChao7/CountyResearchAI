"""存储层。

负责原始数据落盘与缓存:
    - base.py    抽象接口 Storage
    - local_fs.py 本地文件系统实现:按 data/raw/{县名}/{日期}/ 组织
    - cache.py   简易缓存:同一县+方向在 TTL 内复用数据,避免重复调用 API

数据分两层:
    - data/raw/       采集层原始输出(JSON/HTML 快照)
    - data/processed/ 清洗后结构化数据,供 LLM 消费
"""
from __future__ import annotations
