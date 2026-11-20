from __future__ import annotations

from types import SimpleNamespace

from county_research_ai.llm.client import OpenAICompatibleClient


class _FakeCompletions:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            model="deepseek-flash",
            choices=[SimpleNamespace(message=SimpleNamespace(content="报告正文"))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        )


def test_deepseek_defaults_to_disabled_thinking_for_report_content():
    completions = _FakeCompletions()
    client = object.__new__(OpenAICompatibleClient)
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client._model = "deepseek-flash"
    client._settings = SimpleNamespace(llm=SimpleNamespace(provider="deepseek"))

    response = client._do_chat(
        messages=[{"role": "user", "content": "写报告"}],
        temperature=0.0,
        max_tokens=2048,
    )

    assert response.content == "报告正文"
    assert completions.kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
