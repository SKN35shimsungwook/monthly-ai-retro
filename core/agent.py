"""종합 AI 활용 분석 에이전트 (LangGraph).

섹션 하나를 쓰는 그래프
    queries → retrieve → write(Gemini 컨설턴트) → verify ─┬─ 통과 → END
                                   ▲                    └─ 실패(최대 2번 재시도) ─┘
리포트 = 섹션 그래프를 섹션마다 돌린 뒤 summary를 쓰고, 목표 후보는 숫자로 정한다.
질문하기 = retrieve → answer → verify(근거 ID 확인) → 재시도.
"""
import json
import re
from datetime import date, datetime
from typing import Callable, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from core import search, stats, store
from core.analysis import REPORT_DIR, validate
from core.llm import CONSULTANT_SYSTEM, parse_json, text_of
from core.metrics import METRIC_BY_KEY, fmt
from core.redact import find_leaks

MAX_ATTEMPTS = 3
_ID = re.compile(r"\[([A-Z])-(\d+)\]")

# 섹션별 검색 질의와 요청 형식
SECTION_SPEC = {
    "usage": {
        "queries": ["만들어줘 프로그램 게임 앱", "커밋하고 푸시 배포 streamlit", "링크줘 서버 실행",
                    "질문하면서 계획 세워", "리드미 보고서 발표 자료", "자료 조사 딥리서치 pdf"],
        "ask": '이 사람이 AI로 무엇을 만들었고 어떻게 일을 시키는지 정리하라.\n'
               '{"overview": "2~3문장", "made": [{"category": "", "examples": "", "note": ""}] (4~6개),'
               ' "how": ["일을 시키는 흐름 단계"] (4~6개), "habits": ["눈에 띄는 습관 + 근거 [ID] 또는 숫자"] (4~6개)}',
    },
    "strengths": {
        "queries": ["점검표 만들어서 점검 검증", "규칙 정리 마스터 규칙", "질문하면서 계획 세워 확인",
                    "원본이랑 같아 답 같음 오류", "비용 토큰 아까워 무료", "팀 브랜치 건드리지 말고 경계",
                    "끝까지 배포 완성", "봇 시뮬레이션 검증 평가"],
        "ask": '근거가 분명한 강점 5~7개.\n{"items": [{"title": "강점 이름(짧게)", "d4": "위임|설명|분별|책임",'
               ' "evidence": "근거 요약 + [ID] (숫자 있으면 포함)", "why": "왜 강점인가, 컨설턴트 시각 1~2문장"}]}',
    },
    "weaknesses": {
        "queries": ["다 확인했다며 아직도 안돼", "다시 해 제대로 해", "오류 떠 에러 Traceback",
                    "진행해 ㄱㄱ 계속", "사용량 한도", "잔디 커밋 날짜", "왜 안되는 거야",
                    "한번에 추가하고 바꾸고 수정하고"],
        "ask": '근거가 분명한 약점 5~7개. 고칠 수 있는 행동으로 표현.\n{"items": [{"title": "", "d4": "위임|설명|분별|책임",'
               ' "evidence": "근거 요약 + [ID] + 숫자", "why": "왜 문제인가, 어떤 손해가 나는가 1~2문장"}]}',
    },
    "recommendations": {
        "queries": ["다 확인했다며 다시 점검", "한번에 여러 기능 추가 수정", "설명해줘 이해가 안돼",
                    "오류 떠 에러", "진행해 계속"],
        "ask": '약점을 고칠 실행 계획 5~8개, 우선순위 순.\n{"items": [{"priority": 1, "title": "", "now": "지금 하는 방식(근거 [ID])",'
               ' "better": "바로 복사해 AI에게 보낼 수 있는 한국어 요청 문장"}]}',
    },
    "person": {
        "queries": ["친구 같이 놀 재밌게", "팀원 합의 공유 디스코드", "쉽게 설명 초등학생 비유",
                    "자격증 시험 공부 퀴즈", "채용 평가 직무 기술영업", "숫자 환수율 기준 몇 초"],
        "ask": '이 사람을 관찰한 내용(진단 아님). 각 2~4개, 근거 [ID] 포함.\n'
               '{"technical": [], "working": [], "learning": [], "social": [], "motivation": []}',
    },
    "change": {
        "queries": ["계획 세워 단계 진행", "점검 검증 테스트", "고쳐줘 셀 하나로", "다 확인했다며"],
        "ask": '변화 4~6개. 통계의 before/after 숫자와 기록을 근거로.\n{"items": [{"item": "지표나 습관", "before": "", "after": "",'
               ' "verdict": "좋아짐|그대로|나빠짐"}]}',
    },
}


class SectionState(TypedDict, total=False):
    deep: bool           # 초기 총정리: 더 많이, 달마다 골고루 근거를 찾는다
    section: str
    since: str
    until: str
    sources: list[str] | None
    facts: dict          # 통계·이전 리포트 피드백 등 숫자 근거
    queries: list[str]
    hits: list[dict]
    draft: dict
    errors: list[str]
    attempts: int


def _evidence_block(hits: list[dict]) -> str:
    lines = []
    for h in hits:
        one = " ".join(h["text"].split())[:280]
        lines.append(f"[{h['doc']}] ({h['ts'][:10]}, {store.SOURCES[h['source']][0]}, {h['title'][:30]}) {one}")
    return "\n".join(lines)


def _all_numbers(facts: dict) -> set[float]:
    nums = set()

    def walk(x):
        if isinstance(x, bool):
            return
        if isinstance(x, (int, float)):
            nums.add(round(float(x), 1))
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(facts)
    return nums


def check_section(section: str, draft: dict, hit_ids: set[str], facts: dict) -> list[str]:
    """형식 · 근거 ID · 퍼센트 숫자 · 민감정보 검사. 문제를 문장으로 돌려준다."""
    errs = []
    text = json.dumps(draft, ensure_ascii=False)
    cited = {f"{a}-{b}" for a, b in _ID.findall(text)}
    unknown = sorted(cited - hit_ids)
    if unknown:
        errs.append(f"검색 결과에 없는 근거 ID를 썼다: {', '.join(unknown[:8])}. 주어진 목록의 ID만 쓸 것")
    if section in ("strengths", "weaknesses"):
        items = draft.get("items", [])
        if len(items) < 3:
            errs.append("항목이 3개보다 적다")
        for i, it in enumerate(items):
            for f in ("title", "evidence", "why"):
                if not str(it.get(f, "")).strip():
                    errs.append(f"items[{i}].{f} 가 비었다")
            if not _ID.search(str(it.get("evidence", ""))):
                errs.append(f"items[{i}] 근거에 [ID]가 없다")
    elif section == "recommendations":
        for i, it in enumerate(draft.get("items", [])):
            if not it.get("better") or not it.get("now"):
                errs.append(f"items[{i}] 의 now/better 가 비었다")
    elif section == "usage":
        for f in ("overview", "made", "how", "habits"):
            if not draft.get(f):
                errs.append(f"'{f}' 가 비었다")
    elif section == "person":
        for f in ("technical", "working", "learning", "social", "motivation"):
            if not draft.get(f):
                errs.append(f"'{f}' 가 비었다")
    elif section == "change" and not draft.get("items"):
        errs.append("변화 항목이 없다")
    known = _all_numbers(facts)
    for num in re.findall(r"(\d+(?:\.\d+)?)\s*%", text):
        if round(float(num), 1) not in known:
            errs.append(f"통계에 없는 비율 {num}% 를 썼다. 통계 숫자만 쓸 것")
    leaks = find_leaks(text)
    if leaks:
        errs.append(f"민감정보로 보이는 문자열: {leaks}")
    return errs


def build_section_graph(llm):
    def plan(state: SectionState) -> SectionState:
        return {"queries": SECTION_SPEC[state["section"]]["queries"], "attempts": 0, "errors": []}

    def retrieve(state: SectionState) -> SectionState:
        seen, hits = set(), []

        def add(found):
            for h in found:
                if h.doc not in seen:
                    seen.add(h.doc)
                    hits.append(h.__dict__)

        deep = state.get("deep")
        for q in state["queries"]:
            add(search.search(q, k=8 if deep else 6, since=state["since"], until=state["until"], sources=state.get("sources")))
        if deep:  # 달마다 골고루: 초반 기록이 최근 기록에 묻히지 않게
            for m_since, m_until in month_ranges(state["since"], state["until"]):
                for q in state["queries"][:3]:
                    add(search.search(q, k=2, since=m_since, until=m_until, sources=state.get("sources")))
        return {"hits": hits[:70] if deep else hits[:36]}

    def write(state: SectionState) -> SectionState:
        spec = SECTION_SPEC[state["section"]]
        prompt = (f"## 기간\n{state['since']} ~ {state['until']}\n\n## 통계(숫자는 여기 있는 것만)\n"
                  f"{json.dumps(state['facts'], ensure_ascii=False)}\n\n## 검색된 기록\n{_evidence_block(state['hits'])}\n\n"
                  f"## 할 일\n{spec['ask']}")
        if state.get("errors"):
            prompt += "\n\n## 이전 답의 문제 (반드시 고칠 것)\n- " + "\n- ".join(state["errors"])
        reply = llm.invoke([SystemMessage(CONSULTANT_SYSTEM), HumanMessage(prompt)])
        try:
            draft = parse_json(text_of(reply))
        except (ValueError, json.JSONDecodeError) as exc:
            draft = {"_error": str(exc)}
        return {"draft": draft, "attempts": state.get("attempts", 0) + 1}

    def verify(state: SectionState) -> SectionState:
        if "_error" in state["draft"]:
            return {"errors": [f"JSON 형식이 아니다: {state['draft']['_error']}"]}
        ids = {h["doc"] for h in state["hits"]}
        return {"errors": check_section(state["section"], state["draft"], ids, state["facts"])}

    def route(state: SectionState) -> str:
        return "write" if state["errors"] and state["attempts"] < MAX_ATTEMPTS else END

    g = StateGraph(SectionState)
    g.add_node("plan", plan)
    g.add_node("retrieve", retrieve)
    g.add_node("write", write)
    g.add_node("verify", verify)
    g.add_edge(START, "plan")
    g.add_edge("plan", "retrieve")
    g.add_edge("retrieve", "write")
    g.add_edge("write", "verify")
    g.add_conditional_edges("verify", route, {"write": "write", END: END})
    return g.compile()


def month_ranges(since: str, until: str) -> list[tuple[str, str]]:
    """기간을 달 단위 (시작일, 끝일) 목록으로."""
    import calendar

    y, m = int(since[:4]), int(since[5:7])
    out = []
    while f"{y}-{m:02d}" <= until[:7]:
        first = max(f"{y}-{m:02d}-01", since)
        last = min(f"{y}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}", until)
        out.append((first, last))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _goal_candidates(m: dict) -> list[dict]:
    """목표 후보: 좋아질 여지가 큰 지표 4개를 숫자로 정한다(LLM에 맡기지 않음)."""
    picks = []
    for key, target_fn in (("criteria_rate", lambda v: max(15, round(v * 2))), ("evidence_rate", lambda v: max(15, round(v * 2))),
                           ("why_rate", lambda v: max(15, round(v * 1.5))), ("long_session_count", lambda v: max(1, v // 2)),
                           ("redo_count", lambda v: max(5, round(v * 0.6)))):
        v = m.get(key)
        if v is None:
            continue
        target = target_fn(v)
        mm = METRIC_BY_KEY[key]
        sign = "이상" if mm.better == "up" else "이하"
        picks.append({"metric": key, "target": target, "text": f"{mm.label} {fmt(key, target)} {sign} (지금 {fmt(key, v)})"})
    return picks[:4]


def _facts(since: str, until: str, sources, previous: dict | None, prev_me: dict | None) -> dict:
    s = stats.period_stats(since, until, sources)
    facts = {"이번": s}
    from core import profile

    prof = profile.load()
    if prof:  # 사용자가 알려 준 서비스별 용도·빈도 (분업 구조를 해석하는 기준)
        facts["사용_실태"] = {"자주_쓰는_순서": prof["ranking"],
                           "용도": {k: [profile.USES[u][0] for u in v if u in profile.USES] for k, v in prof["uses"].items()}}
    reports = stats.self_reports(sources)
    if reports:  # 각 AI가 자기 기억으로 써 준 '내 사용 보고서' (서비스 내부 관점)
        facts["각_AI가_본_나"] = reports
    if previous and previous.get("metrics"):
        facts["지난_리포트"] = {"period": previous["period"], "metrics": previous["metrics"], "totals": previous.get("totals")}
    else:  # 첫 리포트: 기간 앞 1/3 과 뒤 1/3 비교
        d0, d1 = date.fromisoformat(since).toordinal(), date.fromisoformat(until).toordinal()
        third = max((d1 - d0) // 3, 1)
        early_end = date.fromordinal(d0 + third).isoformat()
        late_start = date.fromordinal(d1 - third).isoformat()
        facts["초반"] = stats.period_stats(since, early_end, sources)["metrics"]
        facts["최근"] = stats.period_stats(late_start, until, sources)["metrics"]
    if prev_me:
        facts["사용자가_틀렸다고_한_관찰"] = prev_me.get("disliked", [])
        facts["지난_목표"] = prev_me.get("goals", [])
    return facts


def generate_report(llm, since: str, until: str, label: str, kind: str, sources: list[str] | None = None,
                    previous: dict | None = None, prev_me: dict | None = None,
                    progress: Callable[[str], None] = lambda _m: None, model_name: str = "",
                    searcher=None, inventory: dict | None = None) -> dict:
    graph = build_section_graph(llm)
    deep = kind == "초기 총정리"
    facts = _facts(since, until, sources, previous, prev_me)
    out: dict = {}
    used_docs: set[str] = set()
    warnings: list[str] = []
    for section in ("usage", "strengths", "weaknesses", "recommendations", "change", "person"):
        progress(f"{section}: 검색 → 작성 → 검증")
        result = graph.invoke({"section": section, "since": since, "until": until, "sources": sources, "facts": facts,
                               "deep": deep})
        draft = result.get("draft", {})
        if result.get("errors"):
            warnings.append(f"{section}: {result['errors'][0]}")
        progress(f"{section}: 완료 (시도 {result.get('attempts')}회)")
        out[section] = draft.get("items", draft) if section in ("strengths", "weaknesses", "recommendations", "change") else draft
        used_docs |= {f"{a}-{b}" for a, b in _ID.findall(json.dumps(draft, ensure_ascii=False))}

    tools = None
    if searcher is not None:
        from core import recommend

        progress("연계 추천: 웹 검색 → 추천 작성 → 출처 검증")
        tools = recommend.recommend(llm, searcher, out["weaknesses"], inventory or {})
        progress(f"연계 추천: 완료 (추천 {len(tools['items'])}개, 시도 {tools['attempts']}회)")
        if tools["warnings"]:
            warnings.append(f"연계 추천: {tools['warnings'][0]}")

    baseline_extra = {}
    if deep:
        from core import baseline

        progress("월별 흐름: 달마다 숫자 계산 → 한 줄 요약 → 검증")
        baseline_extra["monthly"] = baseline.monthly_flow(llm, since, until, sources)
        if searcher is not None:
            progress("AI를 잘 쓰는 사람들의 특징: 웹 검색 → 정리 → 출처 검증")
            baseline_extra["research"] = baseline.best_practices(llm, searcher)

    progress("summary: 요약 작성")
    summary_prompt = ("아래 섹션 결과를 바탕으로 요약을 써라.\n"
                      '{"headline": "기간 전체를 한두 문장으로", "type": "사용 유형 한 줄", "strengths_top": ["3개"],'
                      ' "weaknesses_top": ["3개"], "first_action": "가장 먼저 할 일 한 문장"}\n\n'
                      + json.dumps({k: out[k] for k in ("usage", "strengths", "weaknesses", "recommendations")}, ensure_ascii=False))
    summary = parse_json(text_of(llm.invoke([SystemMessage(CONSULTANT_SYSTEM), HumanMessage(summary_prompt)])))

    s = facts["이번"]
    ids = [store.parse_doc_id(d) for d in used_docs]
    docs = store.get_by_ids([i for i in ids if i])
    data = {
        "label": label, "kind": kind, "period": {"since": since, "until": until},
        "author": f"AI 컨설턴트 에이전트 ({model_name or 'LLM'})",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "sources": s["sources"],
        "headline": summary.get("headline", ""),
        "summary": {k: summary.get(k, "" if k in ("type", "first_action") else []) for k in
                    ("type", "strengths_top", "weaknesses_top", "first_action")},
        "usage": out["usage"], "strengths": out["strengths"], "weaknesses": out["weaknesses"],
        "recommendations": out["recommendations"], "change": out["change"], "person": out["person"],
        "goal_candidates": _goal_candidates(s["metrics"]),
        "tools": (tools or {}).get("items", []),
        **baseline_extra,
        "totals": {**s["totals"]}, "metrics": s["metrics"],
        "evidence_docs": {store.doc_id(d["source"], d["id"]): {"ts": d["ts"][:16], "source": store.SOURCES[d["source"]][0],
                                                               "title": d["title"], "text": d["text"][:400]}
                          for d in docs.values()},
        "limits": ["검색으로 고른 일부 기록과 통계만 보고 쓴 분석이다",
                   "키워드 규칙으로 센 지표는 방향을 보는 용도다",
                   "'나라는 사람'은 진단이 아니라 AI 앞에서 보인 행동의 관찰이다"] + warnings,
    }
    return data


def save_report(data: dict) -> list[str]:
    errs = validate(data)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / f"{data['label']}.analysis.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return errs


# ---------------- 질문하기 ----------------
class AskState(TypedDict, total=False):
    question: str
    since: str | None
    until: str | None
    sources: list[str] | None
    hits: list[dict]
    answer: dict
    errors: list[str]
    attempts: int


def build_ask_graph(llm):
    def retrieve(state: AskState) -> AskState:
        hits = search.search(state["question"], k=14, since=state.get("since"), until=state.get("until"),
                             sources=state.get("sources"))
        return {"hits": [h.__dict__ for h in hits], "attempts": 0, "errors": []}

    def answer(state: AskState) -> AskState:
        prompt = (f"## 질문\n{state['question']}\n\n## 검색된 기록\n{_evidence_block(state['hits']) or '(없음)'}\n\n"
                  '## 할 일\n기록만 근거로 컨설턴트로서 답하라. 기록에 없으면 모른다고 말하라.\n'
                  '{"answer": "3~6문장, 주장마다 [ID]", "advice": "바로 해 볼 행동 1개(없으면 빈 문자열)"}')
        if state.get("errors"):
            prompt += "\n\n## 이전 답의 문제\n- " + "\n- ".join(state["errors"])
        reply = llm.invoke([SystemMessage(CONSULTANT_SYSTEM), HumanMessage(prompt)])
        try:
            ans = parse_json(text_of(reply))
        except (ValueError, json.JSONDecodeError):
            ans = {"answer": text_of(reply), "advice": ""}
        return {"answer": ans, "attempts": state.get("attempts", 0) + 1}

    def verify(state: AskState) -> AskState:
        ids = {h["doc"] for h in state["hits"]}
        text = json.dumps(state["answer"], ensure_ascii=False)
        cited = {f"{a}-{b}" for a, b in _ID.findall(text)}
        errs = []
        if cited - ids:
            errs.append(f"목록에 없는 ID: {', '.join(sorted(cited - ids))}")
        if state["hits"] and not cited:
            errs.append("근거 ID를 하나도 붙이지 않았다")
        return {"errors": errs}

    def route(state: AskState) -> str:
        return "answer" if state["errors"] and state["attempts"] < MAX_ATTEMPTS else END

    g = StateGraph(AskState)
    g.add_node("retrieve", retrieve)
    g.add_node("answer", answer)
    g.add_node("verify", verify)
    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "answer")
    g.add_edge("answer", "verify")
    g.add_conditional_edges("verify", route, {"answer": "answer", END: END})
    return g.compile()
