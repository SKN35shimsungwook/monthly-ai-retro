"""내 PC에서만 실행하는 수집기.

Claude Code 기록 · GitHub · 주간회고 블로그를 모아, 민감정보를 가린 요약 파일
data/summaries/<라벨>.json 을 만든다. 이 파일만 회고 앱에 올린다.

사용 예
    python collector/collect.py --month 2026-11            # 한 달
    python collector/collect.py --initial                  # 처음부터 오늘까지(초기 총정리)
    python collector/collect.py --since 2026-10-01 --until 2026-10-31 --label 2026-10
"""
import argparse
import calendar
import json
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import blog, claude_logs, github_activity  # noqa: E402
from core.redact import find_leaks  # noqa: E402

CONFIG = ROOT / "config.local.json"
OVERRIDES = ROOT / "data" / "rules_override.json"
OUT_DIR = ROOT / "data" / "summaries"


def load_config() -> dict:
    if CONFIG.exists():
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    return {}


def first_log_date(root: Path) -> date:
    earliest = None
    for path in root.glob("*/*.jsonl"):
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if '"timestamp"' not in line:
                    continue
                try:
                    ts = claude_logs._ts(json.loads(line).get("timestamp"))
                except json.JSONDecodeError:
                    continue
                if ts:
                    earliest = ts.date() if earliest is None else min(earliest, ts.date())
                    break
    return earliest or date.today()


def main() -> None:
    p = argparse.ArgumentParser(description="월간 AI 활용 회고 수집기")
    p.add_argument("--month", help="YYYY-MM")
    p.add_argument("--initial", action="store_true", help="기록 처음부터 오늘까지 초기 총정리")
    p.add_argument("--since")
    p.add_argument("--until")
    p.add_argument("--label")
    p.add_argument("--no-github", action="store_true")
    args = p.parse_args()

    cfg = load_config()
    logs_root = Path(cfg.get("claude_projects_dir") or claude_logs.DEFAULT_ROOT)
    names = cfg.get("redact_names", [])
    overrides = json.loads(OVERRIDES.read_text(encoding="utf-8")) if OVERRIDES.exists() else {}

    if args.initial:
        since, until = first_log_date(logs_root), date.today()
        label, kind = "0-initial", "초기 총정리"
    elif args.month:
        y, m = map(int, args.month.split("-"))
        since, until = date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
        label, kind = args.month, "월간"
    elif args.since and args.until:
        since, until = date.fromisoformat(args.since), date.fromisoformat(args.until)
        label, kind = args.label or f"{since}_{until}", "기간"
    else:
        today = date.today()
        y, m = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
        since, until = date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
        label, kind = f"{y}-{m:02d}", "월간"

    print(f"[1/3] Claude Code 기록 집계 중… ({since} ~ {until})")
    claude = claude_logs.collect(since, until, logs_root, names, overrides)
    print(f"      세션 {claude['sessions']}개, 메시지 {claude['user_messages']}개")

    if args.no_github:
        github = {"error": "건너뜀"}
    else:
        print("[2/3] GitHub 활동 집계 중… (저장소가 많으면 1~2분)")
        github = github_activity.collect(since, until)
        print(f"      {github.get('error') or str(github['commits']) + '개 커밋'}")

    print("[3/3] 주간회고 블로그 글 확인 중…")
    posts = blog.collect(since, until, cfg.get("blog_history_path"))

    summary = {
        "version": 1,
        "label": label,
        "kind": kind,
        "period": {"since": since.isoformat(), "until": until.isoformat()},
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "claude": claude,
        "github": github,
        "blog": posts,
    }
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    leaks = find_leaks(json.dumps(claude["examples"], ensure_ascii=False), names)
    if leaks:
        print(f"  ! 예시 문장에 가려지지 않은 항목이 있어 예시를 비웁니다: {leaks}")
        summary["claude"]["examples"] = {}
        text = json.dumps(summary, ensure_ascii=False, indent=2)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{label}.json"
    out.write_text(text, encoding="utf-8")
    print(f"완료: {out}")


if __name__ == "__main__":
    main()
