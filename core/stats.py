"""DB에서 기간·출처별 숫자를 계산한다. 리포트의 숫자 근거이자, 검증 단계의 기준값."""
from collections import Counter, defaultdict

from core import store
from core.metrics import METRICS, classify, is_work_request


def period_stats(since: str, until: str, sources: list[str] | None = None) -> dict:
    rows = store.messages(since, until, sources, role=None)
    users = [r for r in rows if r["role"] == "user"]
    work = [r for r in users if is_work_request(r["text"])]
    by_conv = defaultdict(list)
    for r in users:
        by_conv[r["conversation_id"]].append(r)

    hit, work_hit = Counter(), Counter()
    for r in users:
        h = classify(r["text"])
        hit.update(h)
        if is_work_request(r["text"]):
            work_hit.update(h)

    sizes = sorted(len(v) for v in by_conv.values())
    spans = [(_day(v[-1]["ts"]) - _day(v[0]["ts"])) for v in by_conv.values()]
    values = {}
    for m in METRICS:
        if m.kind == "rate":
            values[m.key] = round(work_hit[m.key] * 100 / len(work), 1) if work else None
        elif m.key == "interrupt_count":
            values[m.key] = sum(1 for r in rows if r["role"] == "event")
        elif m.key == "limit_count":
            values[m.key] = sum(1 for r in users if "사용량 한도" in r["text"])
        elif m.key == "session_median_msgs":
            values[m.key] = sizes[len(sizes) // 2] if sizes else None
        elif m.key == "long_session_count":
            values[m.key] = sum(1 for s in sizes if s >= 50)
        elif m.key == "multi_day_session_count":
            values[m.key] = sum(1 for d in spans if d >= 3)
        else:
            values[m.key] = hit[m.key]

    hours = Counter(int(r["ts"][11:13]) for r in users)
    longest = max(by_conv.values(), key=len) if by_conv else []
    return {
        "period": {"since": since, "until": until},
        "sources": dict(Counter(r["source"] for r in users)),
        "totals": {"sessions": len(by_conv), "user_messages": len(users), "work_requests": len(work),
                   "active_days": len({r["ts"][:10] for r in users}),
                   "commits": sum(1 for r in rows if r["role"] == "commit")},
        "metrics": values,
        "peak_hour": max(hours, key=hours.get) if hours else None,
        "daytime_share": round(sum(n for h, n in hours.items() if 9 <= h < 18) * 100 / len(users)) if users else None,
        "longest_session": {"title": longest[0]["title"], "messages": len(longest),
                            "start": longest[0]["ts"][:10], "end": longest[-1]["ts"][:10]} if longest else None,
        "session_titles": sorted({v[0]["title"] for v in by_conv.values() if v[0]["title"]})[:60],
    }


def monthly_activity() -> list[dict]:
    """타임라인용: 월 × 출처별 내 메시지 수."""
    out = Counter()
    for r in store.messages(role=("user", "commit")):
        out[(r["ts"][:7], r["source"])] += 1
    return [{"월": m, "출처": store.SOURCES[s][0], "메시지": n} for (m, s), n in sorted(out.items())]


def self_reports(sources: list[str] | None = None, limit: int = 2500) -> dict:
    """각 AI가 써 준 사용 보고서(최신 것) — 서비스별로 앞부분만."""
    out: dict[str, str] = {}
    for r in reversed(store.messages(role="self_report", sources=sources)):
        name = store.SOURCES[r["source"]][0]
        if len(out.get(name, "")) < limit:
            out[name] = (out.get(name, "") + "\n" + r["text"])[:limit]
    return out


def _day(ts: str):
    from datetime import date
    return date.fromisoformat(ts[:10]).toordinal()
