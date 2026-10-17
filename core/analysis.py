"""Claude Code가 쓰는 월간 분석 리포트의 형식과 검사.

reports/<라벨>.analysis.json  ← Claude Code가 대화를 읽고 작성 (월간 리포트 스킬)
reports/<라벨>.me.json        ← 앱에서 내가 누른 반응·고른 목표·메모 (자동 저장)
"""
import json
from datetime import datetime
from pathlib import Path

from core.metrics import METRIC_BY_KEY

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports"

# 섹션: (키, 제목, 앵커)
SECTIONS = [
    ("summary", "요약", "summary"),
    ("monthly", "월별 흐름", "monthly"),
    ("usage", "사용 유형과 방식", "usage"),
    ("research", "AI를 잘 쓰는 사람들의 특징", "research"),
    ("strengths", "강점", "strengths"),
    ("weaknesses", "약점", "weaknesses"),
    ("recommendations", "보완점과 추천", "recommendations"),
    ("change", "지난 기간 대비 변화", "change"),
    ("person", "나라는 사람", "person"),
    ("tools", "연계 추천", "tools"),
]

PERSON_PARTS = [("technical", "기술적 면"), ("working", "일하는 방식"), ("learning", "배우는 방식"),
                ("social", "사회적 면"), ("motivation", "동기와 진로")]

EXAMPLE = {
    "label": "2026-11",
    "kind": "월간",
    "period": {"since": "2026-11-01", "until": "2026-11-30"},
    "author": "Claude Code",
    "generated_at": "2026-12-01T09:00:00",
    "headline": "한 문장 결론(이번 기간을 한 줄로)",
    "summary": {
        "type": "사용 유형 한 줄 (예: 감독형 사용자)",
        "strengths_top": ["핵심 강점 1", "핵심 강점 2", "핵심 강점 3"],
        "weaknesses_top": ["핵심 약점 1", "핵심 약점 2", "핵심 약점 3"],
        "first_action": "가장 먼저 할 일 한 문장",
    },
    "usage": {
        "overview": "무엇을 만들고 어떻게 시켰는지 2~3문장",
        "made": [{"category": "종류", "examples": "대표 예", "note": "비중·특징"}],
        "how": ["일을 시키는 흐름 단계"],
        "habits": ["눈에 띄는 습관(근거 숫자 포함)"],
    },
    "strengths": [{"title": "강점 이름", "d4": "위임|설명|분별|책임",
                   "evidence": "실제 대화 근거(가린 인용·숫자)", "why": "왜 강점인가"}],
    "weaknesses": [{"title": "약점 이름", "d4": "위임|설명|분별|책임",
                    "evidence": "실제 대화 근거", "why": "왜 문제인가"}],
    "recommendations": [{"title": "바꿀 것", "now": "지금 하는 방식", "better": "이렇게 (바로 쓸 요청 문장)",
                         "priority": 1}],
    "change": [{"item": "지표나 습관", "before": "지난 기간", "after": "이번 기간", "verdict": "좋아짐|그대로|나빠짐"}],
    "person": {"technical": ["관찰"], "working": ["관찰"], "learning": ["관찰"],
               "social": ["관찰"], "motivation": ["관찰"]},
    "goal_candidates": [{"metric": "criteria_rate", "target": 15, "text": "끝난 기준 붙인 요청 15% 이상"}],
    "limits": ["이 분석의 한계"],
}


def validate(data: dict) -> list[str]:
    """빠진 항목이나 잘못된 값을 사람이 읽을 수 있는 문장으로 돌려준다."""
    errs = []
    for key in ("label", "period", "headline", "summary", "usage", "strengths", "weaknesses",
                "recommendations", "person", "goal_candidates"):
        if key not in data:
            errs.append(f"'{key}' 항목이 없습니다")
    for key in ("strengths", "weaknesses"):
        for i, item in enumerate(data.get(key, [])):
            for f in ("title", "evidence", "why"):
                if not item.get(f):
                    errs.append(f"{key}[{i}].{f} 가 비었습니다")
    for i, r in enumerate(data.get("recommendations", [])):
        for f in ("title", "now", "better"):
            if not r.get(f):
                errs.append(f"recommendations[{i}].{f} 가 비었습니다")
    for i, g in enumerate(data.get("goal_candidates", [])):
        if g.get("metric") not in METRIC_BY_KEY:
            errs.append(f"goal_candidates[{i}].metric '{g.get('metric')}' 는 없는 지표입니다")
    return errs


def list_reports() -> list[dict]:
    """저장된 분석 리포트를 기간 순서대로."""
    out = []
    for p in sorted(REPORT_DIR.glob("*.analysis.json")) if REPORT_DIR.exists() else []:
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return sorted(out, key=lambda d: d.get("period", {}).get("since", ""))


def me_path(label: str) -> Path:
    return REPORT_DIR / f"{label}.me.json"


def load_me(label: str) -> dict:
    p = me_path(label)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"reactions": {}, "goals": [], "note": ""}


def save_me(label: str, me: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    me = {**me, "updated_at": datetime.now().isoformat(timespec="seconds")}
    me_path(label).write_text(json.dumps(me, ensure_ascii=False, indent=2), encoding="utf-8")


# ---- 숫자 붙이기 · 목표 확인 · 마크다운 내보내기 ----

def attach_metrics(data: dict, summary: dict) -> dict:
    """수집기 요약의 숫자를 리포트에 붙인다(배포판은 요약 파일 없이 리포트만 보므로)."""
    c = summary["claude"]
    gh = summary.get("github", {})
    data["totals"] = {
        "sessions": c["sessions"], "user_messages": c["user_messages"], "active_days": c["active_days"],
        "commits": None if gh.get("error") else gh.get("commits"),
        "new_repos": None if gh.get("error") else len(gh.get("repos_created", [])),
        "blog_posts": len(summary.get("blog", {}).get("posts", [])),
    }
    data["metrics"] = {k: v.get("value") for k, v in c["metrics"].items()}
    return data


def goal_met(goal: dict, value) -> bool | None:
    if value is None or goal.get("metric") not in METRIC_BY_KEY:
        return None
    m = METRIC_BY_KEY[goal["metric"]]
    return value >= goal["target"] if m.better == "up" else value <= goal["target"]


def check_goals(previous_me: dict | None, current: dict) -> list[dict]:
    """지난 리포트에서 고른 목표를 이번 리포트 숫자로 확인."""
    if not previous_me:
        return []
    now = current.get("metrics", {})
    return [{**g, "value": now.get(g["metric"]), "achieved": goal_met(g, now.get(g["metric"]))}
            for g in previous_me.get("goals", [])]


def to_markdown(data: dict, me: dict | None = None) -> str:
    """블로그·보관용 마크다운. 내가 👎 한 항목은 뺀다."""
    me = me or {"reactions": {}}
    down = {k for k, v in me.get("reactions", {}).items() if v == 0}
    s = data["summary"]
    p = data["period"]
    title = (f"[AI 활용 회고] 0회차 초기 총정리 ({p['since']} ~ {p['until']})" if data.get("kind") == "초기 총정리"
             else f"[월간 AI 회고] {p['since'][:4]}년 {int(p['since'][5:7])}월")
    out = [f"# {title}", "", f"> {data['headline']}", "", "## 요약", "",
           f"- 사용 유형: {s['type']}",
           f"- 강점: {' / '.join(s['strengths_top'])}",
           f"- 약점: {' / '.join(s['weaknesses_top'])}",
           f"- 먼저 할 일: {s['first_action']}", ""]
    for key, head in (("strengths", "강점"), ("weaknesses", "약점")):
        out += [f"## {head}", ""]
        for i, it in enumerate(data[key]):
            if f"{key}.{i}" in down:
                continue
            out += [f"- **{it['title']}** — {it['why']}", f"  - 근거: {it['evidence']}"]
        out.append("")
    out += ["## 보완점", ""]
    for r in sorted(data["recommendations"], key=lambda r: r.get("priority", 99)):
        out.append(f"{r.get('priority', '-')}. **{r['title']}**: {r['now']} → {r['better']}")
    out.append("")
    if data.get("change"):
        out += ["## 변화", "", "| 항목 | 전 | 후 | 판단 |", "| --- | --- | --- | --- |"]
        out += [f"| {c['item']} | {c['before']} | {c['after']} | {c['verdict']} |" for c in data["change"]]
        out.append("")
    tools = [t for i, t in enumerate(data.get("tools", [])) if f"tools.{i}" not in down]
    if tools:
        out += ["## 연계 추천", ""]
        for t in tools:
            link = f" ([출처]({t['links'][0]['uri']}))" if t.get("links") else ""
            out.append(f"- **{t['name']}** ({t.get('kind', '')}) — {t.get('synergy', '')} 첫 단계: {t.get('first_step', '')}{link}")
        out.append("")
    if me.get("goals"):
        out += ["## 다음 목표", ""] + [f"- {g['text']}" for g in me["goals"]] + [""]
    if me.get("note", "").strip():
        out += ["## 내 한 줄", "", me["note"].strip(), ""]
    return "\n".join(out).rstrip() + "\n"
