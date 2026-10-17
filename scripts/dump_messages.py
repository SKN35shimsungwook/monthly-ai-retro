"""월간 분석용: 기간 안의 내 메시지(가린 것)를 세션별로 한 파일에 모은다.

Claude Code(월간 리포트 스킬)가 이 파일을 읽고 reports/<라벨>.analysis.json 을 쓴다.
결과는 data/summaries/<라벨>.messages.md (커밋되지 않음).

    python scripts/dump_messages.py --label 0-initial
    python scripts/dump_messages.py --label 2026-11
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import claude_logs  # noqa: E402

MAX_LEN = 600  # 붙여넣은 긴 로그는 앞부분만


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--label", required=True, help="data/summaries/<라벨>.json 의 기간을 그대로 쓴다")
    args = p.parse_args()

    summary = json.loads((ROOT / "data" / "summaries" / f"{args.label}.json").read_text(encoding="utf-8"))
    cfg_path = ROOT / "config.local.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    since = date.fromisoformat(summary["period"]["since"])
    until = date.fromisoformat(summary["period"]["until"])
    root = Path(cfg.get("claude_projects_dir") or claude_logs.DEFAULT_ROOT)

    data = claude_logs.collect(since, until, root, cfg.get("redact_names", []), keep_messages=True)
    lines = [f"# 내 메시지 모음 {since} ~ {until} (세션 {len(data['messages_by_session'])}개)", ""]
    for i, s in enumerate(data["messages_by_session"], 1):
        lines.append(f"## {i}. {s['title']} ({len(s['messages'])}개)")
        for when, text in s["messages"]:
            one = " ⏎ ".join(text.splitlines())
            if len(one) > MAX_LEN:
                one = one[:MAX_LEN] + f" …[+{len(one) - MAX_LEN}자]"
            lines.append(f"- {when} {one}")
        lines.append("")
    out = ROOT / "data" / "summaries" / f"{args.label}.messages.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(out, f"({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
