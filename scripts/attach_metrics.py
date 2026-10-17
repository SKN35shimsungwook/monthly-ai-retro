"""수집기 요약(data/summaries/<라벨>.json)의 숫자를 reports/<라벨>.analysis.json 에 붙인다.

    python scripts/attach_metrics.py 0-initial
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.analysis import REPORT_DIR, attach_metrics  # noqa: E402

label = sys.argv[1]
summary = json.loads((ROOT / "data" / "summaries" / f"{label}.json").read_text(encoding="utf-8"))
path = REPORT_DIR / f"{label}.analysis.json"
data = attach_metrics(json.loads(path.read_text(encoding="utf-8")), summary)
path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print("숫자를 붙였습니다:", path.name)
