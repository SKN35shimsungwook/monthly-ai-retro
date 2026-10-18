"""초기 총정리(기준선)에만 붙는 섹션.

- monthly_flow : 처음 달부터 이번 달까지, 달마다 숫자(통계) + 한 줄 요약. 타임라인의 출발점이 된다.
- best_practices : AI를 잘 쓰는 사람들의 특징과 방법을 웹에서 조사(출처 필수). 처음 보고서의 '조사' 섹션과 같은 역할.
둘 다 '작성 → 검증 → 실패하면 이유를 붙여 다시 작성(최대 2번)'.
"""
import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from core import stats
from core.agent import month_ranges
from core.llm import CONSULTANT_SYSTEM, parse_json, text_of

MAX_ATTEMPTS = 3
KEY_METRICS = ("criteria_rate", "plan_first_rate", "evidence_rate", "why_rate", "redo_count", "long_session_count")
_S = re.compile(r"\bS(\d+)\b")


def _ask(llm, prompt: str) -> dict:
    try:
        return parse_json(text_of(llm.invoke([SystemMessage(CONSULTANT_SYSTEM), HumanMessage(prompt)])))
    except (ValueError, json.JSONDecodeError) as exc:
        return {"_error": str(exc)}


def monthly_flow(llm, since: str, until: str, sources: list[str] | None = None) -> list[dict]:
    months = []
    for m0, m1 in month_ranges(since, until):
        s = stats.period_stats(m0, m1, sources)
        if not s["totals"]["user_messages"] and not s["totals"].get("commits"):
            continue
        months.append({"month": m0[:7], "totals": s["totals"],
                       "metrics": {k: s["metrics"].get(k) for k in KEY_METRICS},
                       "titles": s["session_titles"][:10]})
    if not months:
        return []
    expected = [m["month"] for m in months]
    reports = stats.self_reports(sources)
    base = ("달마다 무엇을 했고 AI 활용 방식이 어떻게 달라졌는지 한 줄씩 써라. 숫자는 아래 통계에 있는 것만.\n"
            f"## 달별 통계\n{json.dumps(months, ensure_ascii=False)}\n\n## 각 AI가 쓴 보고서(월별 변화 참고)\n"
            f"{json.dumps(reports, ensure_ascii=False)[:5000]}\n\n"
            '{"months": [{"month": "YYYY-MM", "summary": "그달의 흐름 한 문장", "highlight": "대표 작업 한 가지"}]}'
            f"\n달 목록(이것만, 빠짐없이): {', '.join(expected)}")
    errors: list[str] = []
    out: dict = {}
    for _ in range(MAX_ATTEMPTS):
        prompt = base + ("\n\n## 이전 답의 문제\n- " + "\n- ".join(errors) if errors else "")
        out = _ask(llm, prompt)
        got = [m.get("month") for m in out.get("months", [])]
        errors = []
        if out.get("_error"):
            errors.append(f"JSON 형식이 아니다: {out['_error']}")
        if sorted(got) != sorted(expected):
            errors.append(f"달 목록이 다르다. 써야 할 달: {', '.join(expected)} / 쓴 달: {', '.join(map(str, got))}")
        if any(not m.get("summary") for m in out.get("months", [])):
            errors.append("summary 가 빈 달이 있다")
        if not errors:
            break
    text = {m.get("month"): m for m in out.get("months", [])}
    return [{**{k: v for k, v in m.items() if k != "titles"},
             "summary": text.get(m["month"], {}).get("summary", ""),
             "highlight": text.get(m["month"], {}).get("highlight", "")} for m in months]


RESEARCH_PROMPT = """AI(대화형 AI·코딩 에이전트)를 잘 활용하는 사람들의 특징과 방법을 Google 검색으로 조사하라.
1. 실험·조사 연구: 생산성·품질·학습에 미친 영향 (예: 컨설턴트 대상 현장 실험, 숙련 개발자 실험, AI 사용과 학습·비판적 사고 연구)
2. 공식 모범 사례: Anthropic·OpenAI·Google 의 프롬프트·에이전트 사용 가이드, AI Fluency 같은 역량 프레임워크
각 자료의 핵심 결과(숫자 포함)와 출처를 정리하라."""

WRITE_PROMPT = """## 조사 결과
{research}

## 출처 목록 (이 번호만 쓸 것)
{sources}

## 할 일
연구 4~6개와, 거기서 뽑은 'AI를 잘 쓰는 사람들의 특징' 6~8개를 정리하라. 숫자는 조사 결과에 있는 것만.
{{"studies": [{{"name": "연구·자료 이름", "finding": "핵심 결과 한두 문장(숫자 포함)", "sources": ["S1"]}}],
  "traits": [{{"trait": "특징 한 줄", "how": "실제로 하는 행동 한두 문장", "sources": ["S2"]}}]}}"""


def check_research(draft: dict, n_sources: int) -> list[str]:
    errs = []
    if len(draft.get("studies", [])) < 3:
        errs.append("연구가 3개보다 적다")
    if len(draft.get("traits", [])) < 4:
        errs.append("특징이 4개보다 적다")
    for key in ("studies", "traits"):
        for i, it in enumerate(draft.get(key, [])):
            nums = [int(x) for s in it.get("sources", []) for x in _S.findall(str(s))]
            if not nums:
                errs.append(f"{key}[{i}] 에 출처 S번호가 없다")
            elif any(n < 1 or n > n_sources for n in nums):
                errs.append(f"{key}[{i}] 출처 번호가 S1~S{n_sources} 밖이다")
    return errs


def best_practices(llm, searcher) -> dict:
    from core.recommend import NO_SOURCES, search_with_sources

    research, sources = search_with_sources(searcher, RESEARCH_PROMPT)
    if not sources:  # 출처 없이 쓰면 연구 이름·수치를 지어낸다 → 비워 둔다
        return {"studies": [], "traits": [], "warnings": [NO_SOURCES]}
    src = "\n".join(f"S{i}: {s['title']} {s['uri']}" for i, s in enumerate(sources, 1)) or "(출처 없음)"
    base = WRITE_PROMPT.format(research=research[:7000], sources=src)
    errors: list[str] = []
    draft: dict = {}
    for _ in range(MAX_ATTEMPTS):
        draft = _ask(llm, base + ("\n\n## 이전 답의 문제\n- " + "\n- ".join(errors) if errors else ""))
        errors = ([f"JSON 형식이 아니다: {draft['_error']}"] if draft.get("_error") else []) + check_research(draft, len(sources))
        if not errors:
            break

    def links(it):
        return [sources[int(x) - 1] for s in it.get("sources", []) for x in _S.findall(str(s)) if 1 <= int(x) <= len(sources)]

    # 실제 출처가 안 붙은 항목은 버린다
    return {"studies": [{**s, "links": links(s)} for s in draft.get("studies", []) if links(s)],
            "traits": [{**t, "links": links(t)} for t in draft.get("traits", []) if links(t)],
            "warnings": errors}
