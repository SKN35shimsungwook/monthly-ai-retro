"""연계 추천: 내 약점·지금 쓰는 도구를 보고, 결합하면 시너지가 나는 새 기술·플러그인·스킬·MCP를 웹에서 찾아 추천한다.

LangGraph
    needs(약점·사용 도구 정리) → research(웹 검색, 출처 수집, 0개면 한 번 더) → write(컨설턴트 JSON)
    → verify(출처 번호·이미 쓰는 도구 중복·필수 칸) ─ 실패 시 write 재시도(최대 2번)
없는 도구를 지어내지 않도록, 추천마다 실제 검색 결과 출처 [S번호]를 붙여야 통과한다.
출처가 끝까지 0개면 write 를 건너뛰고 추천을 비워 둔다.
"""
import json
import re
from typing import Callable, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from core.llm import CONSULTANT_SYSTEM, call_with_retry, parse_json, provider_of, text_of

MAX_ATTEMPTS = 3
_S = re.compile(r"\bS(\d+)\b")

RESEARCH_PROMPT = """너는 AI 도구 동향을 조사하는 리서처다. 오늘 기준 최신 정보를 Google 검색으로 찾아라.

## 이 사람이 이미 쓰는 것
{inventory}

## 이 사람의 약점과 필요
{needs}

## 조사할 것
위 약점을 줄이거나, 이미 쓰는 도구와 결합했을 때 시너지가 큰 것을 찾아라.
- Claude Code 플러그인·스킬·서브에이전트·훅·MCP 서버
- ChatGPT·Gemini의 기능(GPTs·Gem·프로젝트·딥리서치·NotebookLM 등)
- 개발·자동화 도구, 새 기술(예: 평가 자동화, 프롬프트 관리, 지식 관리)
후보 8~12개를 찾고, 각각 이름 · 무엇인지 · 공식 문서나 신뢰할 만한 출처 · 이 사람에게 맞는 이유를 정리하라.
이미 쓰는 것과 같은 것은 빼라."""

WRITE_PROMPT = """## 조사 결과
{research}

## 출처 목록 (이 번호만 쓸 것)
{sources}

## 이 사람의 약점
{needs}

## 이미 쓰는 것 (추천 금지)
{inventory}

## 할 일
연계 추천 5~7개. 지금 쓰는 도구와의 결합 시너지가 분명한 것 우선, 시작하기 쉬운 것 먼저.
{{"items": [{{"name": "이름", "kind": "스킬|플러그인|MCP|기능|도구|기술",
  "what": "무엇인지 한 문장", "synergy": "지금 쓰는 무엇과 결합해 무엇이 편해지나 1~2문장",
  "for_weakness": "해결하는 약점 제목(위 목록에서)", "first_step": "오늘 바로 해 볼 첫 단계 한 문장",
  "effort": "낮음|중간|높음", "sources": ["S1"]}}]}}"""


class RecState(TypedDict, total=False):
    weaknesses: list[dict]
    inventory: dict
    needs: str
    research: str
    sources: list[dict]
    draft: dict
    errors: list[str]
    attempts: int


def gemini_web_search(api_key: str, model: str, notify=None) -> Callable[[str], tuple[str, list[dict]]]:
    """Google 검색이 연결된 Gemini 호출. (조사 글, 출처 목록[{title, uri}])을 돌려준다."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    def once(prompt: str) -> tuple[str, list[dict]]:
        resp = client.models.generate_content(
            model=model, contents=prompt,
            config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())], temperature=0.2))
        sources, seen = [], set()
        for cand in resp.candidates or []:
            meta = getattr(cand, "grounding_metadata", None)
            for ch in (getattr(meta, "grounding_chunks", None) or []):
                web = getattr(ch, "web", None)
                if web and web.uri and web.uri not in seen:
                    seen.add(web.uri)
                    sources.append({"title": web.title or "", "uri": web.uri})
        return resp.text or "", sources

    return lambda prompt: call_with_retry(lambda: once(prompt), "gemini", notify)


def _get(obj, key, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def openai_sources(resp) -> tuple[list[dict], bool]:
    """Responses API 응답에서 (출처 목록, 웹 검색을 실제로 했는지)를 뽑는다.
    출처는 두 곳에 있다: message 의 output_text.annotations(url_citation, 제목 있음)와
    web_search_call.action.sources(include 로 요청해야 옴, 제목 없음). 둘 다 모아 URL 기준으로 합친다."""
    sources, seen, searched = [], {}, False

    def add(url, title=""):
        if not url:
            return
        if url in seen:
            if title and not sources[seen[url]]["title"]:
                sources[seen[url]]["title"] = title
            return
        seen[url] = len(sources)
        sources.append({"title": title or "", "uri": url})

    for item in _get(resp, "output", None) or []:
        kind = _get(item, "type", "")
        if kind in ("web_search_call", "web_search_preview_call"):
            searched = True
            for src in _get(_get(item, "action", None), "sources", None) or []:
                add(_get(src, "url"))
        for part in _get(item, "content", None) or []:
            for ann in _get(part, "annotations", None) or []:
                if _get(ann, "type", "") == "url_citation":
                    add(_get(ann, "url"), _get(ann, "title", "") or "")
    # 인용으로 달린 출처(제목 있음)를 앞으로
    sources.sort(key=lambda x: not x["title"])
    return sources, searched


def openai_web_search(api_key: str, model: str, notify=None) -> Callable[[str], tuple[str, list[dict]]]:
    """웹 검색 도구가 붙은 ChatGPT 호출(Responses API). 답 속 인용 링크와 검색 결과 URL을 출처 목록으로 모은다.
    tool_choice 를 'required' 로 둬서 모델이 검색 없이 기억으로 답하는 것을 막는다(gpt-4o-mini 는 auto 면 검색을 건너뛰기도 한다)."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key, max_retries=0, timeout=300)

    def once(prompt: str) -> tuple[str, list[dict]]:
        try:
            resp = client.responses.create(model=model, input=prompt, tools=[{"type": "web_search"}],
                                           tool_choice="required", include=["web_search_call.action.sources"])
        except Exception as exc:  # 예전 모델은 web_search_preview 만 받고 include 도 모른다
            msg = str(exc)
            if not any(k in msg for k in ("web_search", "include", "tool")):
                raise
            resp = client.responses.create(model=model, input=prompt, tools=[{"type": "web_search_preview"}],
                                           tool_choice="required")
        sources, searched = openai_sources(resp)
        if not searched and notify:
            notify(":orange[웹 검색 도구가 호출되지 않았습니다]")
        return _get(resp, "output_text", "") or "", sources

    return lambda prompt: call_with_retry(lambda: once(prompt), "openai", notify)


NO_SOURCES = "웹 검색 출처가 0개라 이 섹션은 비워 둠 (출처 없는 내용을 지어내지 않음)"
RETRY_HINT = ("\n\n반드시 웹 검색 도구로 실제 페이지를 찾아 읽고, 문장마다 그 페이지의 인용 링크를 달아라. "
              "검색으로 확인하지 못한 숫자·이름은 쓰지 마라.")


def search_with_sources(searcher: Callable[[str], tuple[str, list[dict]]], prompt: str,
                        tries: int = 2) -> tuple[str, list[dict]]:
    """출처가 0개면 검색을 강조한 프롬프트로 다시 검색한다(최대 tries 번). 끝까지 0개면 ('', [])."""
    for i in range(tries):
        text, sources = searcher(prompt if i == 0 else prompt + RETRY_HINT)
        if sources:
            return text, sources
    return "", []


def web_search(api_key: str, model: str, notify=None):
    """모델에 맞는 웹 검색기. ChatGPT 모델이면 OpenAI 웹 검색, 아니면 Gemini + Google 검색."""
    if provider_of(model) == "openai":
        return openai_web_search(api_key, model, notify)
    return gemini_web_search(api_key, model, notify)


def _installed_names(inventory: dict) -> list[str]:
    names = list(inventory.get("claude_code_skills_installed", []))
    names += [k.split(":")[-1].split("@")[0] for k in inventory.get("skills_used", {})]
    names += [k.split("@")[0] for k in inventory.get("plugins_used", {})]
    names += inventory.get("mcp_servers", [])
    return sorted({n.lower() for n in names if n})


def check(draft: dict, n_sources: int, inventory: dict, weakness_titles: list[str]) -> list[str]:
    errs = []
    items = draft.get("items", [])
    if len(items) < 3:
        errs.append("추천이 3개보다 적다")
    installed = _installed_names(inventory)
    for i, it in enumerate(items):
        for f in ("name", "what", "synergy", "first_step"):
            if not str(it.get(f, "")).strip():
                errs.append(f"items[{i}].{f} 가 비었다")
        nums = [int(x) for s in it.get("sources", []) for x in _S.findall(str(s))]
        if not nums:
            errs.append(f"items[{i}] '{it.get('name')}' 에 출처 S번호가 없다")
        elif any(n < 1 or n > n_sources for n in nums):
            errs.append(f"items[{i}] 출처 번호가 목록(S1~S{n_sources}) 밖이다")
        if str(it.get("name", "")).lower() in installed:
            errs.append(f"'{it.get('name')}' 는 이미 쓰는 것이다")
    if weakness_titles and not any(it.get("for_weakness") in weakness_titles for it in items):
        errs.append("약점 목록의 제목과 연결된 추천이 하나도 없다")
    return errs


def build_graph(llm, searcher: Callable[[str], tuple[str, list[dict]]]):
    def needs(state: RecState) -> RecState:
        lines = [f"- {w.get('title')}: {w.get('why', '')}" for w in state["weaknesses"]]
        return {"needs": "\n".join(lines), "attempts": 0, "errors": []}

    def research(state: RecState) -> RecState:
        inv = json.dumps(state["inventory"], ensure_ascii=False)
        text, sources = search_with_sources(searcher, RESEARCH_PROMPT.format(inventory=inv, needs=state["needs"]))
        if not sources:  # 출처 없이 쓰면 지어낸 추천이 된다 → 쓰지 않고 끝낸다
            return {"research": "", "sources": [], "draft": {"items": []}, "errors": [NO_SOURCES]}
        return {"research": text, "sources": sources}

    def write(state: RecState) -> RecState:
        src = "\n".join(f"S{i}: {s['title']} {s['uri']}" for i, s in enumerate(state["sources"], 1)) or "(출처 없음)"
        prompt = WRITE_PROMPT.format(research=state["research"][:6000], sources=src, needs=state["needs"],
                                     inventory=", ".join(_installed_names(state["inventory"])))
        if state.get("errors"):
            prompt += "\n\n## 이전 답의 문제 (반드시 고칠 것)\n- " + "\n- ".join(state["errors"])
        try:
            draft = parse_json(text_of(llm.invoke([SystemMessage(CONSULTANT_SYSTEM), HumanMessage(prompt)])))
        except (ValueError, json.JSONDecodeError) as exc:
            draft = {"items": [], "_error": str(exc)}
        return {"draft": draft, "attempts": state.get("attempts", 0) + 1}

    def verify(state: RecState) -> RecState:
        titles = [w.get("title", "") for w in state["weaknesses"]]
        errs = check(state["draft"], len(state["sources"]), state["inventory"], titles)
        if state["draft"].get("_error"):
            errs.insert(0, f"JSON 형식이 아니다: {state['draft']['_error']}")
        return {"errors": errs}

    def route(state: RecState) -> str:
        return "write" if state["errors"] and state["attempts"] < MAX_ATTEMPTS else END

    g = StateGraph(RecState)
    for name, fn in (("needs", needs), ("research", research), ("write", write), ("verify", verify)):
        g.add_node(name, fn)
    g.add_edge(START, "needs")
    g.add_edge("needs", "research")
    g.add_conditional_edges("research", lambda st: "write" if st["sources"] else END, {"write": "write", END: END})
    g.add_edge("write", "verify")
    g.add_conditional_edges("verify", route, {"write": "write", END: END})
    return g.compile()


def recommend(llm, searcher, weaknesses: list[dict], inventory: dict) -> dict:
    """리포트에 넣을 형태: {"items": [...출처 URL 포함], "sources": {...}, "warnings": [...]}"""
    out = build_graph(llm, searcher).invoke({"weaknesses": weaknesses, "inventory": inventory})
    sources = out.get("sources", [])
    items = []
    for it in out.get("draft", {}).get("items", []):
        links = []
        for s in it.get("sources", []):
            for x in _S.findall(str(s)):
                n = int(x)
                if 1 <= n <= len(sources):
                    links.append(sources[n - 1])
        if links:  # 실제 출처가 안 붙은 추천은 버린다
            items.append({**it, "links": links})
    return {"items": items, "warnings": out.get("errors", []), "attempts": out.get("attempts")}
