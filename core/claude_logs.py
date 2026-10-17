"""Claude Code 대화 기록(~/.claude/projects/*/*.jsonl) 집계.

원문은 이 PC 밖으로 나가지 않는다. 요약 파일에는 숫자와,
지표마다 가린 예시 문장 최대 3개(120자 이내)만 들어간다.
"""
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from core.metrics import METRICS, classify, is_work_request
from core.redact import redact

KST = timezone(timedelta(hours=9))
DEFAULT_ROOT = Path.home() / ".claude" / "projects"

_SKIP_PREFIX = ("<local-command", "<command-", "Caveat:", "This session is being continued",
                "<task-notification>", "<side-sessions-event>", "<artifact-view-context",
                "<artifact-content-authored-by-others")
_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
_LIMIT = "사용량 한도"


def _ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(KST)
    except ValueError:
        return None


def _user_texts(message: dict) -> list[str]:
    content = message.get("content")
    if isinstance(content, str):
        return [content]
    out = []
    for part in content or []:
        if isinstance(part, dict) and part.get("type") == "text":
            out.append(part.get("text", ""))
    return out


def collect(since: date, until: date, root: Path = DEFAULT_ROOT,
            names: list[str] | None = None, overrides: dict | None = None,
            keep_messages: bool = False) -> dict:
    """since~until(KST, 양 끝 포함) 기간의 Claude Code 사용 요약.

    keep_messages=True 이면 세션별 내 메시지 원문(가린 것)을 함께 돌려준다.
    월간 분석을 쓸 Claude Code가 읽는 용도이며, 요약 파일에는 넣지 않는다.
    """
    seen_msgs: set[tuple] = set()
    seen_tools: set[str] = set()
    sessions: dict[str, dict] = defaultdict(lambda: {"msgs": [], "title": "", "cwd": Counter()})
    tools = Counter()
    models = Counter()
    hours = Counter()
    weekdays = Counter()
    days = set()
    interrupts = 0
    modes = Counter()

    for path in sorted(root.glob("*/*.jsonl")):
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rtype = rec.get("type")
                sid = rec.get("sessionId") or path.stem
                if rtype in ("custom-title", "ai-title"):
                    title = rec.get("customTitle") or rec.get("aiTitle") or ""
                    if title and (rtype == "custom-title" or not sessions[sid]["title"]):
                        sessions[sid]["title"] = title
                    continue
                ts = _ts(rec.get("timestamp"))
                if ts is None or not (since <= ts.date() <= until):
                    continue
                msg = rec.get("message") or {}
                if rtype == "assistant":
                    uid = rec.get("uuid", "")
                    if uid in seen_tools:
                        continue
                    seen_tools.add(uid)
                    if msg.get("model") and not msg["model"].startswith("<"):
                        models[msg["model"]] += 1
                    for part in msg.get("content") or []:
                        if isinstance(part, dict) and part.get("type") == "tool_use":
                            tools[part.get("name", "?").split("__")[-1]] += 1
                    continue
                if rtype != "user" or rec.get("isMeta") or rec.get("isSidechain"):
                    continue
                for raw in _user_texts(msg):
                    if "Request interrupted" in raw:
                        key = ("intr", rec.get("timestamp"))
                        if key not in seen_msgs:
                            seen_msgs.add(key)
                            interrupts += 1
                        continue
                    text = _REMINDER.sub("", raw).strip()
                    if not text or text.startswith(_SKIP_PREFIX):
                        continue
                    key = (rec.get("timestamp"), text[:200])
                    if key in seen_msgs:
                        continue
                    seen_msgs.add(key)
                    sessions[sid]["msgs"].append((ts, text))
                    if rec.get("cwd"):
                        sessions[sid]["cwd"][Path(rec["cwd"]).name] += 1
                    if rec.get("permissionMode"):
                        modes[rec["permissionMode"]] += 1
                    hours[ts.hour] += 1
                    weekdays[ts.weekday()] += 1
                    days.add(ts.date())

    all_msgs = [(sid, ts, text) for sid, s in sessions.items() for ts, text in s["msgs"]]
    all_msgs.sort(key=lambda x: x[1])
    work = [m for m in all_msgs if is_work_request(m[2])]

    hit_count = Counter()
    work_hit = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    for _sid, _ts_, text in all_msgs:
        hits = classify(text, overrides)
        for k in hits:
            hit_count[k] += 1
        if is_work_request(text):
            for k in hits:
                work_hit[k] += 1
        for k in hits:
            examples[k].append(text)

    real_sessions = {sid: s for sid, s in sessions.items() if s["msgs"]}
    sizes = sorted(len(s["msgs"]) for s in real_sessions.values())
    spans = []
    for sid, s in real_sessions.items():
        first, last = s["msgs"][0][0], s["msgs"][-1][0]
        spans.append((last - first).days)
    limit_hits = sum(1 for _sid, _t, text in all_msgs if _LIMIT in text)

    def rate(k: str) -> dict:
        n = len(work)
        v = round(work_hit[k] * 100 / n, 1) if n else None
        return {"value": v, "numerator": work_hit[k], "denominator": n}

    values: dict[str, dict] = {}
    for m in METRICS:
        if m.kind == "rate":
            values[m.key] = rate(m.key)
        elif m.key == "interrupt_count":
            values[m.key] = {"value": interrupts}
        elif m.key == "limit_count":
            values[m.key] = {"value": limit_hits}
        elif m.key == "session_median_msgs":
            values[m.key] = {"value": sizes[len(sizes) // 2] if sizes else None}
        elif m.key == "long_session_count":
            values[m.key] = {"value": sum(1 for x in sizes if x >= 50)}
        elif m.key == "multi_day_session_count":
            values[m.key] = {"value": sum(1 for d in spans if d >= 3)}
        else:
            values[m.key] = {"value": hit_count[m.key]}

    def short(text: str) -> str:
        one = " ".join(redact(text, names).split())
        return one[:117] + "…" if len(one) > 120 else one

    example_out = {}
    for k, texts in examples.items():
        picked = [short(t) for t in texts if "<pasted_content" not in t and "$env:" not in t and len(t) >= 8][-3:]
        if picked:
            example_out[k] = picked

    session_list = []
    for sid, s in sorted(real_sessions.items(), key=lambda kv: kv[1]["msgs"][0][0]):
        session_list.append({
            "title": redact(s["title"], names) or "(제목 없음)",
            "folder": s["cwd"].most_common(1)[0][0] if s["cwd"] else "",
            "start": s["msgs"][0][0].date().isoformat(),
            "end": s["msgs"][-1][0].date().isoformat(),
            "messages": len(s["msgs"]),
        })

    lengths = sorted(len(t) for _s, _t, t in all_msgs)
    result = {
        "sessions": len(real_sessions),
        "user_messages": len(all_msgs),
        "work_requests": len(work),
        "active_days": len(days),
        "tool_calls": sum(tools.values()),
        "message_length_median": lengths[len(lengths) // 2] if lengths else None,
        "metrics": values,
        "examples": example_out,
        "hours": {str(h): hours[h] for h in range(24)},
        "weekdays": {str(d): weekdays[d] for d in range(7)},
        "tools_top": tools.most_common(12),
        "models": dict(models.most_common()),
        "permission_modes": dict(modes),
        "folders": Counter(s["folder"] for s in session_list if s["folder"]).most_common(15),
        "session_list": session_list,
    }
    if keep_messages:
        result["messages_by_session"] = [
            {"title": redact(s["title"], names) or "(제목 없음)",
             "messages": [(ts.strftime("%m-%d %H:%M"), redact(text, names)) for ts, text in s["msgs"]]}
            for _sid, s in sorted(real_sessions.items(), key=lambda kv: kv[1]["msgs"][0][0])
        ]
    return result
