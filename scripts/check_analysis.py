"""Claude Code가 쓴 analysis.json 형식 검사 + 민감정보 검사.

    python scripts/check_analysis.py reports/2026-11.analysis.json
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.analysis import validate  # noqa: E402
from core.redact import find_leaks  # noqa: E402


def main() -> None:
    path = Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    cfg_path = ROOT / "config.local.json"
    names = json.loads(cfg_path.read_text(encoding="utf-8")).get("redact_names", []) if cfg_path.exists() else []
    errs = validate(data)
    leaks = find_leaks(text, names)
    for e in errs:
        print("형식:", e)
    if leaks:
        print("민감정보:", leaks)
    if errs or leaks:
        sys.exit(1)
    print("OK", path.name)


if __name__ == "__main__":
    main()
