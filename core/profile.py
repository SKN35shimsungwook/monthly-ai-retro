"""사용 실태 조사: 서비스별로 '무엇에, 얼마나 자주' 쓰는지.

이 답에 맞춰 각 서비스 프롬프트가 '그 용도에서 꼭 확인할 것'을 집중해서 찾게 된다.
저장 위치: data/usage_profile.json (이 PC에만, 커밋 안 됨)
"""
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "data" / "usage_profile.json"

RANK_SOURCES = ["claude_code", "chatgpt", "gemini", "claude_web"]

# 용도 → (보이는 이름, 그 용도에서 꼭 확인할 것, Claude 검색 키워드)
USES = {
    "idea": ("아이디어·기획 상담",
             "어떤 아이디어를 상담했고, 상담 뒤 실제로 만든 것 / 버린 것은 무엇인지. 질문을 어떻게 던졌는지(막연하게 vs 조건을 주고)",
             ["기획", "아이디어", "계획", "만들고 싶"]),
    "research": ("딥리서치·자료 조사",
                 "조사한 주제 목록, 결과 리포트를 어디에 썼는지(다른 AI의 구현 재료·발표·과제), 출처를 확인했는지, 같은 주제를 다시 조사한 적이 있는지",
                 ["리서치", "조사", "자료", "보고서"]),
    "image": ("이미지 생성",
              "무엇을 왜 만들었는지, 원하는 결과까지 몇 번 다시 요청했는지, 결과를 어디에 썼는지(앱·발표·디자인)",
              ["이미지", "그림", "디자인"]),
    "video": ("영상 생성",
              "만든 영상의 용도와 재시도 횟수, 이미지·프롬프트를 어떻게 준비했는지",
              ["영상", "동영상"]),
    "quick": ("검색 대신 빠른 질문",
              "주로 묻는 주제, 검색 대신 AI에 물은 이유, 답을 다른 곳에서 확인했는지",
              ["질문", "알려줘", "뭐야"]),
    "study": ("공부·개념 질문",
              "어떤 과목·개념을 물었는지, 이해될 때까지 다시 물었는지, 문제를 직접 풀고 확인받았는지",
              ["개념", "설명", "공부", "문제"]),
    "writing": ("글쓰기·문서·보고서",
                "어떤 문서를 썼는지(보고서·발표·자기소개서·회고), 초안을 몇 번 고쳤는지, 최종본을 내가 다시 손봤는지",
                ["보고서", "문서", "발표", "대본"]),
    "prototype": ("아티팩트·빠른 시제품",
                  "만든 시제품(게임·페이지·도구) 목록, 공유했는지, 이후 Claude Code 같은 개발 도구로 옮겨 키웠는지",
                  ["아티팩트", "게임", "페이지", "만들어"]),
    "coding": ("코딩·디버깅",
               "어떤 언어·프로젝트였는지, 에러를 그대로 붙여넣었는지, 고친 이유를 이해했는지",
               ["코드", "오류", "에러", "디버그"]),
    "api": ("API로만 사용",
            "채팅보다 내 앱에 API를 붙여 쓰는 용도. 채팅 기록은 적을 수 있다",
            ["API"]),
}

DEFAULT_USES = {"chatgpt": ["idea", "study", "writing"], "gemini": ["research", "quick"], "claude_web": ["writing"]}


def load() -> dict | None:
    if PROFILE_PATH.exists():
        return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    return None


def save(ranking: list[str], uses: dict[str, list[str]], note: str = "") -> dict:
    prof = {"ranking": ranking, "uses": uses, "note": note, "updated": date.today().isoformat()}
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(prof, ensure_ascii=False, indent=2), encoding="utf-8")
    return prof


def rank_of(prof: dict | None, source: str) -> int | None:
    if not prof or source not in prof.get("ranking", []):
        return None
    return prof["ranking"].index(source) + 1


def focus_block(prof: dict | None, source: str, service: str) -> str:
    """프롬프트에 끼워 넣을 '내가 알려 준 사용 실태' 문단. 조사 결과가 없으면 빈 문자열."""
    if not prof:
        return ""
    uses = [u for u in prof.get("uses", {}).get(source, []) if u in USES]
    rank = rank_of(prof, source)
    order = " > ".join(_name(s) for s in prof.get("ranking", []))
    lines = [f"내가 알려 준 사용 실태 (이걸 기준으로 집중해서 찾아라)",
             f"- 자주 쓰는 순서: {order} → {service}는 {rank}순위" if rank else f"- 자주 쓰는 순서: {order}"]
    if uses:
        lines.append(f"- {service}의 주 용도: " + ", ".join(USES[u][0] for u in uses))
        lines.append("- 용도별로 꼭 확인할 것:")
        lines += [f"  · {USES[u][0]}: {USES[u][1]}" for u in uses]
        lines.append("- '## 주로 한 일'은 위 용도마다 '- 용도명:' 소제목으로 나눠 쓴다. 위에 없는 용도로 쓴 흔적이 있으면 '- 그 밖:'에 쓴다.")
    lines.append("- 나는 여러 AI를 이어서 쓴다(예: 조사·기획 → Claude Code로 구현). "
                 f"{service}에서 나온 결과를 다른 AI나 도구로 넘긴 경우 '→ 넘긴 곳'을 함께 적는다.")
    if rank and rank >= 4:
        lines.append(f"- {service}는 자주 쓰지 않는다. 기록이 적으면 적다고 쓰고 억지로 채우지 않는다.")
    return "\n".join(lines)


def search_keywords(prof: dict | None, source: str, base: list[str]) -> list[str]:
    extra = [k for u in (prof or {}).get("uses", {}).get(source, []) if u in USES for k in USES[u][2]]
    return list(dict.fromkeys(extra + base))


def _name(source: str) -> str:
    return {"claude_code": "Claude Code", "chatgpt": "ChatGPT", "gemini": "Gemini", "claude_web": "Claude AI (웹·앱)"}.get(source, source)
