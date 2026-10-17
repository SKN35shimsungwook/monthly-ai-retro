"""모든 AI 사용기록을 한 형식으로 담는 로컬 DB (SQLite).

출처(source): claude_code · claude_web · chatgpt · gemini
메시지는 민감정보를 가린 뒤에만 저장한다. 문서 ID는 "출처약자-번호" (예: G-120) — 리포트 근거로 쓴다.
"""
import sqlite3
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "db" / "history.db"

SOURCES = {
    "claude_code": ("Claude Code", "C"),
    "claude_web": ("Claude AI (웹·앱)", "W"),
    "chatgpt": ("ChatGPT", "P"),
    "gemini": ("Gemini", "G"),
    "github": ("GitHub", "H"),
}

# role: user(내 메시지) · assistant(AI 답) · event(작업 중단 등) · commit(GitHub 커밋) · self_report(각 AI가 써 준 사용 보고서)
#       · artifact(claude.ai에 남은 아티팩트: 제목·주소·날짜)
EVIDENCE_ROLES = ("user", "commit", "self_report", "artifact")

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    ext_id TEXT NOT NULL,
    title TEXT,
    started_at TEXT,
    UNIQUE(source, ext_id)
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    source TEXT NOT NULL,
    role TEXT NOT NULL,          -- user | assistant | event | commit | self_report
    text TEXT NOT NULL,
    ts TEXT NOT NULL,            -- KST ISO 시각
    UNIQUE(conversation_id, role, ts, text)
);
CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(ts);
CREATE INDEX IF NOT EXISTS idx_messages_source ON messages(source);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def doc_id(source: str, message_id: int) -> str:
    return f"{SOURCES[source][1]}-{message_id}"


def parse_doc_id(value: str) -> int | None:
    try:
        return int(value.split("-", 1)[1])
    except (IndexError, ValueError):
        return None


def save_conversations(convs: list[dict], path: Path | None = None) -> dict:
    path = path or DB_PATH
    """convs: [{source, ext_id, title, started_at, messages: [{role, text, ts}]}]. 중복은 건너뛴다."""
    added_conv = added_msg = 0
    with closing(connect(path)) as con, con:
        for c in convs:
            cur = con.execute(
                "INSERT OR IGNORE INTO conversations(source, ext_id, title, started_at) VALUES (?,?,?,?)",
                (c["source"], c["ext_id"], c.get("title") or "", c.get("started_at") or ""))
            if cur.rowcount:
                added_conv += 1
            cid = con.execute("SELECT id FROM conversations WHERE source=? AND ext_id=?",
                              (c["source"], c["ext_id"])).fetchone()["id"]
            for m in c["messages"]:
                if not m.get("text", "").strip():
                    continue
                cur = con.execute(
                    "INSERT OR IGNORE INTO messages(conversation_id, source, role, text, ts) VALUES (?,?,?,?,?)",
                    (cid, c["source"], m["role"], m["text"], m["ts"]))
                added_msg += cur.rowcount
    return {"conversations": added_conv, "messages": added_msg}


def overview(path: Path | None = None) -> list[dict]:
    path = path or DB_PATH
    if not path.exists():
        return []
    with closing(connect(path)) as con:
        rows = con.execute("""
            SELECT m.source, COUNT(DISTINCT m.conversation_id) AS convs,
                   SUM(m.role='user') AS user_msgs, SUM(m.role='commit') AS commits,
                   SUM(m.role='self_report') AS report_parts,
                   MIN(CASE WHEN m.role!='self_report' THEN m.ts END) AS first,
                   MAX(CASE WHEN m.role!='self_report' THEN m.ts END) AS last
            FROM messages m GROUP BY m.source ORDER BY m.source""").fetchall()
    return [dict(r) for r in rows]


def messages(since: str | None = None, until: str | None = None, sources: list[str] | None = None,
             role: str | tuple | None = "user", path: Path | None = None) -> list[dict]:
    """기간(YYYY-MM-DD, 양 끝 포함)·출처·역할로 메시지를 가져온다."""
    path = path or DB_PATH
    sql = ("SELECT m.id, m.source, m.role, m.text, m.ts, m.conversation_id, c.title "
           "FROM messages m JOIN conversations c ON c.id = m.conversation_id WHERE 1=1")
    args: list = []
    if since:
        sql += " AND m.ts >= ?"
        args.append(since)
    if until:
        sql += " AND m.ts < ?"
        args.append(until + "T99")  # 그날 끝까지
    if sources:
        sql += f" AND m.source IN ({','.join('?' * len(sources))})"
        args += sources
    if isinstance(role, (list, tuple)):
        sql += f" AND m.role IN ({','.join('?' * len(role))})"
        args += list(role)
    elif role:
        sql += " AND m.role = ?"
        args.append(role)
    sql += " ORDER BY m.ts"
    if not path.exists():
        return []
    with closing(connect(path)) as con:
        return [dict(r) for r in con.execute(sql, args).fetchall()]


def get_by_ids(ids: list[int], path: Path | None = None) -> dict[int, dict]:
    path = path or DB_PATH
    if not ids or not path.exists():
        return {}
    with closing(connect(path)) as con:
        rows = con.execute(
            "SELECT m.id, m.source, m.role, m.text, m.ts, c.title FROM messages m "
            f"JOIN conversations c ON c.id=m.conversation_id WHERE m.id IN ({','.join('?' * len(ids))})", ids)
        return {r["id"]: dict(r) for r in rows}


def reply_after(message_id: int, path: Path | None = None) -> str:
    path = path or DB_PATH
    """사용자 메시지 바로 다음 AI 답변(맥락용)."""
    with closing(connect(path)) as con:
        row = con.execute("""
            SELECT text FROM messages WHERE conversation_id =
              (SELECT conversation_id FROM messages WHERE id=?) AND role='assistant' AND id > ?
            ORDER BY id LIMIT 1""", (message_id, message_id)).fetchone()
    return row["text"] if row else ""


def replace_conversation(conv: dict, path: Path | None = None) -> dict:
    """같은 (출처, ext_id) 대화를 지우고 새로 넣는다. 같은 날 AI 보고서를 다시 저장할 때 중복을 막는다."""
    path = path or DB_PATH
    with closing(connect(path)) as con, con:
        row = con.execute("SELECT id FROM conversations WHERE source=? AND ext_id=?", (conv["source"], conv["ext_id"])).fetchone()
        if row:
            con.execute("DELETE FROM messages WHERE conversation_id=?", (row["id"],))
            con.execute("DELETE FROM conversations WHERE id=?", (row["id"],))
    return save_conversations([conv], path)
