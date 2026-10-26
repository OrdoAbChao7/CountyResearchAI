# AxiomScope — 90 秒演示脚本

This demo runs entirely offline with `MOCK` search and LLM fixtures. It proves
the product path and the evidence chain. It does **not** measure real retrieval
or model quality.

## Prerequisites

- Windows 10/11 with PowerShell, Python 3.10+, Node 20+.
- From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
cd web
npm install
npm run build
cd ..
```

Linux/WSL equivalent: `python3 -m venv .venv; .venv/bin/pip install -e '.[dev]';
cd web && npm install && npm run build; cd ..`.

## Start

```powershell
.\scripts\start_api.ps1
```

Open <http://127.0.0.1:8000>. The header shows `MOCK` and `API v1`.

## Script (≈90 s)

1. **Submit (15 s).** The form is prefilled with
   `评估德清县 2024 年产业发展与财政健康`, region `德清县`, window
   `2024-01-01 ~ 2024-12-31`. Press **开始研究**.
2. **Timeline (20 s).** The job runs `collect → discover → evidence → analyze →
   report`. Point out the events and the `MOCK` badge. The budget panel shows
   which caps were enforced (`deadline_seconds`, `max_documents`) and which are
   not enforced on this workflow path (`max_steps`, `max_search_calls`,
   `max_cost`).
3. **Evidence (35 s).** Open the 证据 tab. Expand a `已支持` conclusion, then click
   **查看来源**. The right panel opens the immutable source snapshot and
   highlights the exact quote. Expand a `不可比` conclusion: its period (2025 or
   2027) is outside the requested 2024 window, so it is not counted as support.
   Note the checks shown (independent sources, value present, span integrity).
4. **Brief (15 s).** Open 决策简报. Download the Markdown. It contains explicit
   `MOCK` and limitation labels, supported findings with citations, and a
   withheld section that does not restate unsupported claims.
5. **Cancel/resume (5 s, optional).** The mock run finishes quickly; to see the
   durable states, run the API tests or submit a task with a long
   `deadline_seconds` and stop the API process. After restart the job shows
   `已中断`; press **恢复运行**.

## What not to claim

- Do not describe this demo as evidence that AxiomScope beats the legacy
  baselines. Current small-sample offline results do not support that claim.
- Do not call the deterministic checks "semantic entailment".
- Screenshots are not produced by the automated test suite; inspect the UI
  manually or run the API/Selenium checks explicitly.
