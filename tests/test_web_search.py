"""웹 검색 출처 처리: OpenAI 응답 파싱, 0개면 재검색, 끝까지 0개면 지어내지 않고 비워 두기."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import baseline, recommend  # noqa: E402
from core.llm import FakeLLM  # noqa: E402

INVENTORY = {"claude_code_skills_installed": [], "skills_used": {}, "plugins_used": {}, "mcp_servers": []}
WEAK = [{"title": "증거 없이 됐다를 믿음", "why": "확인 안 함"}]
SRC = [{"title": "Docs A", "uri": "https://a.example"}, {"title": "Docs B", "uri": "https://b.example"}]


def _rec(name, src="S1"):
    return {"name": name, "kind": "도구", "what": "w", "synergy": "s", "for_weakness": WEAK[0]["title"],
            "first_step": "f", "effort": "낮음", "sources": [src]}


# ---------------- OpenAI Responses 응답 파싱 ----------------
def _openai_resp(searched=True, action_urls=(), citations=()):
    """Responses API 응답 모양: web_search_call 다음 message(output_text.annotations)."""
    out = []
    if searched:
        out.append(NS(type="web_search_call", status="completed",
                      action=NS(type="search", query="q", sources=[NS(type="url", url=u) for u in action_urls])))
    anns = [NS(type="url_citation", url=u, title=t, start_index=0, end_index=1) for u, t in citations]
    out.append(NS(type="message", role="assistant", content=[NS(type="output_text", text="답", annotations=anns)]))
    return NS(output=out, output_text="답")


def test_openai_sources_reads_citations_and_action_sources():
    resp = _openai_resp(action_urls=["https://x.example", "https://a.example"],
                        citations=[("https://a.example", "Docs A"), ("https://a.example", "Docs A")])
    sources, searched = recommend.openai_sources(resp)
    assert searched
    assert sources == [{"title": "Docs A", "uri": "https://a.example"}, {"title": "", "uri": "https://x.example"}]


def test_openai_sources_accepts_dicts_and_flags_no_search():
    resp = {"output": [{"type": "message", "content": [{"type": "output_text", "annotations": [
        {"type": "url_citation", "url": "https://d.example", "title": "D"}, {"type": "file_citation", "file_id": "f"}]}]}]}
    sources, searched = recommend.openai_sources(resp)
    assert sources == [{"title": "D", "uri": "https://d.example"}] and not searched
    assert recommend.openai_sources(_openai_resp(searched=False)) == ([], False)


def test_openai_web_search_forces_tool_and_requests_sources(monkeypatch):
    calls = []

    class FakeResponses:
        def create(self, **kw):
            calls.append(kw)
            return _openai_resp(citations=[("https://a.example", "Docs A")])

    class FakeOpenAI:
        def __init__(self, **_kw):
            self.responses = FakeResponses()

    import openai
    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    text, sources = recommend.openai_web_search("k", "gpt-4o-mini")("조사해")
    assert calls[0]["tool_choice"] == "required"  # 검색 없이 기억으로 답하는 것을 막음
    assert calls[0]["tools"] == [{"type": "web_search"}]
    assert "web_search_call.action.sources" in calls[0]["include"]
    assert text == "답" and sources == [{"title": "Docs A", "uri": "https://a.example"}]


# ---------------- 0개면 다시 검색 ----------------
def test_search_with_sources_retries_once_then_gives_up():
    prompts = []

    def empty(p):
        prompts.append(p)
        return "지어낸 글", []

    assert recommend.search_with_sources(empty, "조사") == ("", [])
    assert len(prompts) == 2 and "웹 검색 도구" in prompts[1]

    answers = iter([("글1", []), ("글2", SRC)])
    assert recommend.search_with_sources(lambda _p: next(answers), "조사") == ("글2", SRC)


# ---------------- 끝까지 0개면 지어내지 않음 ----------------
def test_recommend_skips_writing_when_no_sources():
    llm = FakeLLM([json.dumps({"items": [_rec("지어낸 도구")] * 3}, ensure_ascii=False)])
    out = recommend.recommend(llm, lambda _p: ("지어낸 조사", []), WEAK, INVENTORY)
    assert out["items"] == [] and out["warnings"] == [recommend.NO_SOURCES]
    assert llm.calls == []  # 작성 단계를 아예 부르지 않음


def test_recommend_drops_items_without_valid_source():
    bad = json.dumps({"items": [_rec("A", "S9"), _rec("B"), _rec("C", "S2")]}, ensure_ascii=False)
    out = recommend.recommend(FakeLLM([bad] * 3), lambda _p: ("조사", SRC), WEAK, INVENTORY)
    assert [it["name"] for it in out["items"]] == ["B", "C"]  # 재시도 다 실패해도 출처 없는 A 는 빠짐
    assert out["warnings"]


def test_best_practices_empty_when_no_sources():
    llm = FakeLLM([json.dumps({"studies": [{"name": "가짜 연구", "finding": "30% 향상", "sources": ["S1"]}]})])
    out = baseline.best_practices(llm, lambda _p: ("조사", []))
    assert out == {"studies": [], "traits": [], "warnings": [recommend.NO_SOURCES]}
    assert llm.calls == []


def test_best_practices_drops_unsourced_numbers():
    draft = {"studies": [{"name": f"연구{i}", "finding": "f", "sources": [f"S{i}"]} for i in (1, 2, 9)],
             "traits": [{"trait": f"특징{i}", "how": "h", "sources": ["S1"]} for i in range(4)]}
    out = baseline.best_practices(FakeLLM([json.dumps(draft, ensure_ascii=False)] * 3), lambda _p: ("조사", SRC))
    assert [s["name"] for s in out["studies"]] == ["연구1", "연구2"] and len(out["traits"]) == 4
