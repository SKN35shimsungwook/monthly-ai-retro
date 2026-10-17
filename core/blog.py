"""주간회고(WIL) 블로그 글 목록. 블로그 자동화 프로그램의 history.json을 읽는다."""
import json
from datetime import date
from pathlib import Path


def collect(since: date, until: date, history_path: str | Path | None) -> dict:
    if not history_path:
        return {"posts": [], "note": "history.json 경로가 설정되지 않았습니다"}
    path = Path(history_path)
    if not path.exists():
        return {"posts": [], "note": f"파일이 없습니다: {path.name}"}
    entries = json.loads(path.read_text(encoding="utf-8"))
    posts = []
    for e in entries:
        d = e.get("date", "")
        if d and since.isoformat() <= d <= until.isoformat():
            posts.append({
                "date": d,
                "title": e.get("title", ""),
                "summary": e.get("one_line_summary", ""),
                "tags": e.get("tags", []),
                "url": e.get("url", ""),
            })
    return {"posts": posts}
