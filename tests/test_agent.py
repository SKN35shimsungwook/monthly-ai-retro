import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import agent, importers, search, stats, store  # noqa: E402
from core.llm import FakeLLM  # noqa: E402

CHATGPT = [{"id": "g1", "title": "파이썬 질문", "create_time": 1791000000, "mapping": {
    "a": {"message": {"author": {"role": "user"}, "create_time": 1791000000,
                      "content": {"parts": ["판다스 groupby 왜 이렇게 동작해? 설명해줘"]}}},
    "b": {"message": {"author": {"role": "assistant"}, "create_time": 1791000010,
                      "content": {"parts": ["groupby는 ..."]}}},
    "c": {"message": {"author": {"role": "system"}, "content": {"parts": ["숨김"]}}}}}]
CLAUDE_WEB = [{"uuid": "w1", "name": "발표 대본", "created_at": "2026-10-02T01:00:00Z", "chat_messages": [
    {"sender": "human", "text": "발표 대본 다듬어줘 끝난 기준: 3분 이내", "created_at": "2026-10-02T01:00:00Z"},
    {"sender": "assistant", "text": "다듬은 대본", "created_at": "2026-10-02T01:00:05Z"}]}]
GEMINI = [{"header": "Gemini Apps", "title": "Prompted EQ 테스트 자료 조사해줘 sk-abcdefghijklmnopqrstuvwx",
           "time": "2026-10-03T02:00:00.000Z", "products": ["Gemini Apps"],
           "safeHtmlItem": [{"html": "<p>EQ 자료입니다</p>"}]},
          {"header": "Search", "title": "Searched for 날씨", "time": "2026-10-03T02:00:00Z", "products": ["Search"]}]


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "db" / "history.db")
    for name, data in (("conversations.json", CHATGPT), ("conversations.json", CLAUDE_WEB), ("MyActivity.json", GEMINI)):
        _label, convs = importers.detect_and_parse(name, json.dumps(data, ensure_ascii=False).encode(), [])
        store.save_conversations(convs)
    search.build()
    return tmp_path


def test_detect_formats_and_redact():
    kind, convs = importers.detect_and_parse("x.json", json.dumps(CHATGPT).encode(), [])
    assert kind == "ChatGPT" and [m["role"] for m in convs[0]["messages"]] == ["user", "assistant"]
    kind, convs = importers.detect_and_parse("x.json", json.dumps(CLAUDE_WEB).encode(), [])
    assert kind == "Claude AI (웹·앱)" and convs[0]["messages"][0]["ts"].endswith("+09:00")
    kind, convs = importers.detect_and_parse("x.json", json.dumps(GEMINI).encode(), [])
    assert kind == "Gemini" and len(convs) == 1  # 검색 활동은 빠짐
    assert "sk-" not in convs[0]["messages"][0]["text"] and "Prompted" not in convs[0]["messages"][0]["text"]


def test_zip_upload():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("export/conversations.json", json.dumps(CHATGPT))
    kind, convs = importers.detect_and_parse("chatgpt.zip", buf.getvalue(), [])
    assert kind == "ChatGPT" and convs


def test_store_dedupes_and_searches(db):
    before = store.overview()
    _k, convs = importers.detect_and_parse("c.json", json.dumps(CHATGPT).encode(), [])
    assert store.save_conversations(convs)["messages"] == 0  # 같은 파일 다시 올려도 중복 없음
    assert store.overview() == before
    hits = search.search("groupby 설명", k=3)
    assert hits and hits[0].doc.startswith("P-")
    assert all(h.source == "gemini" for h in search.search("groupby", sources=["gemini"]))


def test_stats_counts_why_and_criteria(db):
    s = stats.period_stats("2026-09-01", "2026-12-31")
    assert s["totals"]["user_messages"] == 3
    assert s["metrics"]["why_rate"] > 0 and s["metrics"]["criteria_rate"] > 0


def _valid_items(doc: str) -> str:
    return json.dumps({"items": [{"title": f"강점{i}", "d4": "분별", "evidence": f"근거 [{doc}]", "why": "이유"}
                                 for i in range(3)]}, ensure_ascii=False)


def test_section_graph_retries_on_unknown_id(db):
    doc = search.search("판다스 groupby")[0].doc
    llm = FakeLLM([_valid_items("P-99999"), _valid_items(doc)])
    graph = agent.build_section_graph(llm)
    out = graph.invoke({"section": "strengths", "since": "2026-09-01", "until": "2026-12-31",
                        "sources": None, "facts": {"x": 1}})
    assert out["attempts"] == 2 and out["errors"] == []
    second_prompt = llm.calls[1][1].content
    assert "P-99999" in second_prompt  # 검증 실패 이유가 다음 시도에 전달됨


def test_section_check_rejects_made_up_percent():
    errs = agent.check_section("strengths", json.loads(_valid_items("P-1").replace("이유", "요청의 37.5%가 문제")),
                               {"P-1"}, {"metrics": {"criteria_rate": 5.1}})
    assert any("37.5%" in e for e in errs)


def test_ask_graph_answers_with_citation(db):
    doc = search.search("EQ 자료 조사")[0].doc
    llm = FakeLLM([json.dumps({"answer": "근거 없이 답함", "advice": ""}),
                   json.dumps({"answer": f"EQ 자료를 Gemini로 조사했다 [{doc}]", "advice": "출처를 남기자"})])
    out = agent.build_ask_graph(llm).invoke({"question": "EQ 자료 조사"})
    assert doc in out["answer"]["answer"] and out["attempts"] == 2


def test_generate_report_end_to_end(db):
    p = search.search("groupby")[0].doc
    w = search.search("발표 대본")[0].doc
    usage = json.dumps({"overview": f"질문과 문서 작업 [{p}]", "made": [{"category": "학습", "examples": "판다스", "note": ""}],
                        "how": ["질문"], "habits": [f"설명 요청 [{p}]"]}, ensure_ascii=False)
    recs = json.dumps({"items": [{"priority": 1, "title": "기준 먼저", "now": f"그냥 요청 [{w}]", "better": "끝난 기준: ..."}]},
                      ensure_ascii=False)
    change = json.dumps({"items": [{"item": "설명 요청", "before": "-", "after": "늘었다", "verdict": "좋아짐"}]}, ensure_ascii=False)
    person = json.dumps({k: [f"관찰 [{p}]"] for k in ("technical", "working", "learning", "social", "motivation")},
                        ensure_ascii=False)
    summary = json.dumps({"headline": "한 줄", "type": "질문형", "strengths_top": ["a"], "weaknesses_top": ["b"],
                          "first_action": "c"}, ensure_ascii=False)
    llm = FakeLLM([usage, _valid_items(p), _valid_items(w), recs, change, person, summary])
    data = agent.generate_report(llm, "2026-09-01", "2026-12-31", "t", "월간")
    assert data["headline"] == "한 줄" and p in data["evidence_docs"]
    assert data["goal_candidates"] and data["totals"]["user_messages"] == 3
    from core.analysis import validate
    assert validate(data) == []


# ---------------- 자기 보고서 · 연계 추천 ----------------
from core import prompts, recommend  # noqa: E402

REPORT_TEXT = """## 기간과 사용량
2026-08 ~ 2026-10, 대화 약 120개
## 아쉬운 점
한 번에 여러 기능을 요청함 (2026-09-23 카지노)
## 추천
GPTs로 반복 프롬프트 저장"""


def test_prompts_share_headings_but_differ_in_how_to_find():
    texts = {src: prompts.prompt_for(src) for src in ("chatgpt", "gemini", "claude_web")}
    for text in texts.values():
        heads = [ln[3:] for ln in text.splitlines() if ln.startswith("## ")]
        assert heads == prompts.SECTIONS  # 합치기 위해 제목·순서는 같다
    assert "최소 20번" in texts["claude_web"] and "Claude Code" in texts["claude_web"]
    assert "접근할 수 없음" in texts["gemini"] and "Gem" in texts["gemini"]
    assert "메모리" in texts["chatgpt"] and "대략" in texts["chatgpt"]
    assert len({t.split("규칙")[0] for t in texts.values()}) == 3  # 찾는 방법은 서비스마다 다르다
    parts = prompts.split_report(REPORT_TEXT)
    assert [t for t, _ in parts] == ["기간과 사용량", "아쉬운 점", "추천"]


def test_self_report_saved_and_searchable(db):
    convs = importers.self_report("chatgpt", REPORT_TEXT, [], received="2026-10-16T10:00:00+09:00")
    store.save_conversations(convs)
    search.build()
    hits = search.search("한 번에 여러 기능", since="2026-12-01")  # 기간 밖이어도 자기 보고서는 참고
    assert any(h.doc.startswith("P-") and "[아쉬운 점]" in h.text for h in hits)
    assert "ChatGPT" in stats.self_reports()


INVENTORY = {"claude_code_skills_installed": ["skill-creator"], "skills_used": {}, "plugins_used": {}, "mcp_servers": []}
WEAK = [{"title": "증거 없이 됐다를 믿음", "why": "확인 안 함"}]


def _rec(name, src="S1", weak="증거 없이 됐다를 믿음"):
    return {"name": name, "kind": "플러그인", "what": "w", "synergy": "s", "for_weakness": weak,
            "first_step": "f", "effort": "낮음", "sources": [src]}


def test_recommend_check_rules():
    ok = {"items": [_rec("A"), _rec("B"), _rec("C")]}
    assert recommend.check(ok, 2, INVENTORY, ["증거 없이 됐다를 믿음"]) == []
    bad = {"items": [_rec("skill-creator"), _rec("B", "S9"), _rec("C", "", "다른 약점")]}
    errs = recommend.check(bad, 2, INVENTORY, ["증거 없이 됐다를 믿음"])
    assert any("이미 쓰는" in e for e in errs) and any("밖이다" in e for e in errs) and any("출처" in e for e in errs)


def test_recommend_graph_retries_and_attaches_links():
    searched = []

    def fake_search(prompt):
        searched.append(prompt)
        return "조사 결과", [{"title": "Docs A", "uri": "https://a.example"}, {"title": "Docs B", "uri": "https://b.example"}]

    bad = json.dumps({"items": [_rec("A", "S7"), _rec("B"), _rec("C")]}, ensure_ascii=False)
    good = json.dumps({"items": [_rec("A", "S2"), _rec("B"), _rec("C")]}, ensure_ascii=False)
    out = recommend.recommend(FakeLLM([bad, good]), fake_search, WEAK, INVENTORY)
    assert out["attempts"] == 2 and out["warnings"] == []
    assert out["items"][0]["links"][0]["uri"] == "https://b.example"
    assert "skill-creator" in searched[0]  # 이미 쓰는 도구를 알려주고 검색함


# ---------------- 초기 총정리(기준선) ----------------
from core import baseline  # noqa: E402


def test_prompt_modes_scope():
    init = prompts.prompt_for("claude_web", "initial")
    month = prompts.prompt_for("claude_web", "monthly", "2026-11")
    assert "처음 사용한 날부터" in init and "최소 20번" in init and "가장 오래된 달까지" in init
    assert "2026-11 한 달만" in month and "최소 10번" in month
    for t in (init, month):
        assert [ln[3:] for ln in t.splitlines() if ln.startswith("## ")] == prompts.SECTIONS


def test_self_report_modes_do_not_overwrite(db):
    store.save_conversations(importers.self_report("gemini", REPORT_TEXT, [], received="2026-10-16T10:00:00+09:00", mode="initial"))
    store.save_conversations(importers.self_report("gemini", REPORT_TEXT, [], received="2026-10-16T11:00:00+09:00", mode="monthly"))
    convs = {m["title"] for m in store.messages(role="self_report", sources=["gemini"])}
    assert any("초기 전체" in t for t in convs) and any("월간" in t for t in convs)


def test_month_ranges():
    assert agent.month_ranges("2026-07-27", "2026-09-10") == [
        ("2026-07-27", "2026-07-31"), ("2026-08-01", "2026-08-31"), ("2026-09-01", "2026-09-10")]


def _add_month(month: str, text: str):
    store.save_conversations([{"source": "claude_web", "ext_id": f"extra-{month}", "title": "추가", "started_at": "",
                               "messages": [{"role": "user", "text": text, "ts": f"{month}-05T10:00:00+09:00"}]}])
    search.build()


def test_deep_retrieval_spreads_across_months(db):
    _add_month("2026-08", "점검표 만들어서 검증해줘 판다스 groupby")
    llm = FakeLLM([_valid_items(search.search("groupby")[0].doc)])
    out = agent.build_section_graph(llm).invoke({"section": "strengths", "since": "2026-01-01", "until": "2026-12-31",
                                                 "sources": None, "facts": {}, "deep": True})
    months = {h["ts"][:7] for h in out["hits"]}
    assert len(months) >= 2  # 10월 한 달에 몰리지 않음


def test_monthly_flow_retries_until_all_months(db):
    _add_month("2026-11", "11월 메시지 계획 세워줘")
    first = json.dumps({"months": [{"month": "2026-10", "summary": "a", "highlight": ""}]})
    second = json.dumps({"months": [{"month": "2026-10", "summary": "시월", "highlight": "x"},
                                    {"month": "2026-11", "summary": "십일월", "highlight": "y"}]})
    llm = FakeLLM([first, second])
    flow = baseline.monthly_flow(llm, "2026-10-01", "2026-11-30")
    assert [m["month"] for m in flow] == ["2026-10", "2026-11"] and flow[1]["summary"] == "십일월"
    assert "2026-11" in llm.calls[1][1].content  # 빠진 달을 알려 주고 다시 씀


def test_best_practices_requires_sources():
    src = [{"title": f"T{i}", "uri": f"https://s{i}.example"} for i in range(1, 4)]
    good = json.dumps({"studies": [{"name": f"연구{i}", "finding": "f", "sources": ["S1"]} for i in range(3)],
                       "traits": [{"trait": f"특징{i}", "how": "h", "sources": ["S2"]} for i in range(4)]}, ensure_ascii=False)
    bad = good.replace('"S2"', '"S9"')
    out = baseline.best_practices(FakeLLM([bad, good]), lambda _p: ("조사", src))
    assert out["warnings"] == [] and out["traits"][0]["links"][0]["uri"] == "https://s2.example"


GEMINI_NO_ACCESS = """기간과 사용량(처음 쓴 시기 ~ 최근, 대략적인 대화 수)

* 기간: (추측) Bard 시절인 2024년경부터 2026년 10월까지
* 대략적인 대화 수: 기록 없음 (이전 채팅 접근 불가)

주로 한 일(주제별 대략 비중과 대표 예시 5~8개)

* 기록 없음

요청하는 방식(요청 길이)

* 기록 없음

이 서비스가 기억하는 나('저장된 정보')

* 기록 없음"""


def test_split_without_hash_headings_and_detect_empty():
    parts = prompts.split_report(GEMINI_NO_ACCESS)
    assert [t for t, _ in parts] == ["기간과 사용량", "주로 한 일", "요청하는 방식", "이 서비스가 기억하는 나"]
    assert prompts.emptiness(GEMINI_NO_ACCESS) >= 0.7
    assert prompts.emptiness(REPORT_TEXT) == 0


TAKEOUT_HTML = """<html><body>
<div class="outer-cell mdl-cell"><div class="mdl-grid"><div class="header-cell"><p class="mdl-typography--title">Gemini 앱<br></p></div><div class="content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1">SELECT 오류 고쳐줘 항목을 검색함<br>이 채팅에 코딩 파트너이 사용되었습니다. <a href="https://gemini.google.com/gems/view">Gem을 관리하세요.</a><br>2026. 7. 22. 오후 3:40:39 KST<br><p>테이블 이름 오타입니다</p></div><div class="content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1 mdl-typography--text-right"></div><div class="content-cell mdl-typography--caption"><b>세부정보:</b> https://gemini.google.com/app/abc123</div></div></div>
<div class="outer-cell mdl-cell"><div class="mdl-grid"><div class="header-cell"><p class="mdl-typography--title">Gemini 앱<br></p></div><div class="content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1">사진 정장으로 바꿔줘 항목을 검색함<br>이미지 1개가 생성되었습니다.<br>파일 1개 첨부됨.<br>-  <a href="a.png">a.png</a><br>2026. 10. 8. 오전 9:05:08 KST<br><p></p></div><div class="content-cell mdl-typography--caption">https://gemini.google.com/app/abc123</div></div></div>
<div class="outer-cell mdl-cell"><div class="mdl-grid"><div class="content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1">의견을 삭제했습니다.<br>2026. 10. 9. 오전 9:05:08 KST<br></div></div></div>
</body></html>"""


def test_gemini_korean_takeout_html():
    convs = importers.gemini_html(TAKEOUT_HTML, [])
    assert len(convs) == 1 and convs[0]["ext_id"] == "abc123"  # 같은 대화 ID로 묶임, 의견 삭제는 빠짐
    users = [m for m in convs[0]["messages"] if m["role"] == "user"]
    assert users[0]["text"] == "(Gem: 코딩 파트너) SELECT 오류 고쳐줘"
    assert users[1]["text"].startswith("(이미지 1개 생성 · 첨부 1개) 사진 정장으로")
    assert users[0]["ts"] == "2026-07-22T15:40:39+09:00" and users[1]["ts"].startswith("2026-10-08T09:05")
    assert any(m["role"] == "assistant" and "오타" in m["text"] for m in convs[0]["messages"])


def test_from_folder(tmp_path):
    d = tmp_path / "Takeout" / "내 활동" / "Gemini 앱"
    d.mkdir(parents=True)
    (d / "내활동.html").write_text(TAKEOUT_HTML, encoding="utf-8")
    found = importers.from_folder(tmp_path, [])
    assert len(found) == 1 and found[0][1][0]["source"] == "gemini"


def test_resaving_self_report_replaces(db):
    store.replace_conversation(importers.self_report("gemini", REPORT_TEXT, [], received="2026-10-16T10:00:00+09:00")[0])
    store.replace_conversation(importers.self_report("gemini", REPORT_TEXT, [], received="2026-10-16T10:00:40+09:00")[0])
    assert len(store.messages(role="self_report", sources=["gemini"])) == 3  # 두 번 저장해도 한 벌


def test_claude_new_export_zips_and_manifest(tmp_path):
    # 대화 zip: 대화마다 json 하나
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i, conv in enumerate(CLAUDE_WEB):
            z.writestr(f"conversations/{i}.json", json.dumps(conv, ensure_ascii=False))
    kind, convs = importers.detect_and_parse("conversations-000.zip", buf.getvalue(), [])
    assert kind == "Claude AI (웹·앱)" and convs[0]["messages"][0]["role"] == "user"
    # 메모리 zip
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("memories.json", json.dumps({"memory": "부트캠프 수강생, 기술영업 희망", "uuid": "x"}, ensure_ascii=False))
    kind, convs = importers.detect_and_parse("memories-000.zip", buf.getvalue(), [])
    assert kind == "Claude 메모리" and "기술영업" in convs[0]["messages"][0]["text"]
    # 목록표(manifest)는 링크 안내
    manifest = {"data_files": [{"category": "conversations", "filename": "conversations-000.zip", "export_url": "https://claude.ai/export/x"},
                               {"category": "feedback", "filename": "feedback-000.zip", "export_url": "https://claude.ai/export/y"}]}
    with pytest.raises(importers.ManifestError) as e:
        importers.detect_and_parse("manifest-1.json", json.dumps(manifest).encode(), [])
    assert [f["filename"] for f in e.value.files] == ["conversations-000.zip"]
