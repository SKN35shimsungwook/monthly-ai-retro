"""AI 서비스별 내보내기 파일 → 공통 형식 [{source, ext_id, title, started_at, messages:[{role, text, ts}]}].

받는 파일
- Claude Code : 이 PC의 ~/.claude/projects/*/*.jsonl (자동)
- Claude 웹·앱: 설정 → 개인정보 → 데이터 내보내기 → zip 안의 conversations.json
- ChatGPT    : 설정 → 데이터 제어 → 데이터 내보내기 → zip 안의 conversations.json
- Gemini     : Google 테이크아웃 → 'Gemini 앱 활동' → MyActivity.json (또는 .html)
모든 텍스트는 저장 전에 가린다(redact).
"""
import html as htmllib
import io
import json
import re
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.redact import redact

KST = timezone(timedelta(hours=9))
_TAG = re.compile(r"<[^>]+>")
_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
_SKIP = ("<local-command", "<command-", "Caveat:", "This session is being continued", "<task-notification>",
         "<side-sessions-event>", "<artifact-view-context", "<artifact-content-authored-by-others")
MAX_ASSISTANT = 1500  # AI 답변은 맥락용으로 앞부분만


def _iso(value) -> str:
    """여러 형식의 시각 → KST ISO 문자열."""
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(value, tz=timezone.utc)
    else:
        s = str(value).replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return ""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KST).isoformat(timespec="seconds")


def _clean(text: str, names: list[str], limit: int | None = None) -> str:
    text = redact(text.strip(), names)
    return text[:limit] if limit else text


# ---------- Claude Code ----------
def claude_code(root: Path, names: list[str]) -> list[dict]:
    convs: dict[str, dict] = {}
    seen: set[tuple] = set()  # 이어하기·포크로 복사된 세션의 같은 메시지는 한 번만
    for path in sorted(root.glob("*/*.jsonl")):
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                sid = rec.get("sessionId") or path.stem
                conv = convs.setdefault(sid, {"source": "claude_code", "ext_id": sid, "title": "",
                                              "started_at": "", "messages": []})
                rtype = rec.get("type")
                if rtype in ("custom-title", "ai-title"):
                    title = rec.get("customTitle") or rec.get("aiTitle") or ""
                    if title and (rtype == "custom-title" or not conv["title"]):
                        conv["title"] = _clean(title, names)
                    continue
                if rtype not in ("user", "assistant") or rec.get("isMeta") or rec.get("isSidechain"):
                    continue
                ts = _iso(rec.get("timestamp"))
                if not ts:
                    continue
                content = (rec.get("message") or {}).get("content")
                parts = [content] if isinstance(content, str) else [
                    p.get("text", "") for p in content or [] if isinstance(p, dict) and p.get("type") == "text"]
                for raw in parts:
                    if rtype == "user" and "Request interrupted" in raw:
                        conv["messages"].append({"role": "event", "text": "[작업 중단]", "ts": ts})
                        continue
                    text = _REMINDER.sub("", raw).strip()
                    if not text or text.startswith(_SKIP):
                        continue
                    key = (rtype, ts, text[:200])
                    if key in seen:
                        continue
                    seen.add(key)
                    limit = MAX_ASSISTANT if rtype == "assistant" else None
                    conv["messages"].append({"role": rtype, "text": _clean(text, names, limit), "ts": ts})
                    conv["started_at"] = conv["started_at"] or ts
    return [c for c in convs.values() if any(m["role"] == "user" for m in c["messages"])]


# ---------- Claude 웹·앱 (claude.ai 내보내기) ----------
def claude_web(data: list, names: list[str]) -> list[dict]:
    out = []
    for conv in data:
        msgs = []
        for m in conv.get("chat_messages", []):
            text = m.get("text") or "\n".join(
                p.get("text", "") for p in m.get("content", []) if isinstance(p, dict) and p.get("type") == "text")
            role = "user" if m.get("sender") == "human" else "assistant"
            limit = MAX_ASSISTANT if role == "assistant" else None
            msgs.append({"role": role, "text": _clean(text or "", names, limit), "ts": _iso(m.get("created_at"))})
        out.append({"source": "claude_web", "ext_id": conv.get("uuid", ""), "title": _clean(conv.get("name") or "", names),
                    "started_at": _iso(conv.get("created_at")), "messages": [m for m in msgs if m["ts"]]})
    return out


# ---------- ChatGPT ----------
def chatgpt(data: list, names: list[str]) -> list[dict]:
    out = []
    for conv in data:
        nodes = [n.get("message") for n in (conv.get("mapping") or {}).values() if n.get("message")]
        nodes.sort(key=lambda m: m.get("create_time") or 0)
        msgs = []
        for m in nodes:
            role = (m.get("author") or {}).get("role")
            if role not in ("user", "assistant"):
                continue
            parts = (m.get("content") or {}).get("parts") or []
            text = "\n".join(p for p in parts if isinstance(p, str))
            if not text.strip():
                continue
            limit = MAX_ASSISTANT if role == "assistant" else None
            msgs.append({"role": role, "text": _clean(text, names, limit),
                         "ts": _iso(m.get("create_time") or conv.get("create_time"))})
        out.append({"source": "chatgpt", "ext_id": conv.get("id") or conv.get("conversation_id") or conv.get("title", ""),
                    "title": _clean(conv.get("title") or "", names), "started_at": _iso(conv.get("create_time")),
                    "messages": [m for m in msgs if m["ts"]]})
    return out


# ---------- Gemini (Google 테이크아웃 '내 활동') ----------
def gemini(data: list, names: list[str]) -> list[dict]:
    """활동 1건 = 프롬프트 1개(+답변). 같은 날 활동을 한 대화로 묶는다."""
    days: dict[str, dict] = {}
    for item in data:
        title = item.get("title", "")
        if not title or not any("Gemini" in p or "Bard" in p for p in item.get("products", []) + [item.get("header", "")]):
            continue
        prompt = re.sub(r"^(Prompted|Asked|프롬프트 입력:?|질문함:?)\s*", "", title).strip()
        ts = _iso(item.get("time"))
        if not prompt or not ts:
            continue
        day = ts[:10]
        conv = days.setdefault(day, {"source": "gemini", "ext_id": day, "title": f"Gemini {day}",
                                     "started_at": ts, "messages": []})
        conv["messages"].append({"role": "user", "text": _clean(prompt, names), "ts": ts})
        answer = " ".join(htmllib.unescape(_TAG.sub(" ", h.get("html", ""))) for h in item.get("safeHtmlItem", []))
        if answer.strip():
            conv["messages"].append({"role": "assistant", "text": _clean(" ".join(answer.split()), names, MAX_ASSISTANT),
                                     "ts": ts})
    return list(days.values())


# 테이크아웃 HTML 한 칸: "<내 프롬프트> 항목을 검색함<br>(Gem·이미지·첨부 안내)<br>날짜 KST<br><Gemini 답> … 세부정보: gemini.google.com/app/<대화ID>"
_TK_DATE = re.compile(r"<br>\s*(\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.\s*(?:오전|오후)\s*\d{1,2}:\d{2}(?::\d{2})?\s*[A-Z]{2,4})\s*<br>"
                      r"|<br>\s*([A-Z][a-z]{2} \d{1,2}, \d{4}, \d{1,2}:\d{2}:\d{2}\s*[AP]M\s*[A-Z]{2,4})\s*<br>")
_TK_PROMPT_END = re.compile(r"\s*(항목을 검색함|Prompted|Asked)\s*$")
_TK_CHAT = re.compile(r"gemini\.google\.com/app/([0-9a-f]+)")


def _plain(fragment: str) -> str:
    text = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>", "\n", fragment)
    text = htmllib.unescape(_TAG.sub("", text))
    return "\n".join(ln.rstrip() for ln in text.splitlines()).strip()


def gemini_html(text: str, names: list[str]) -> list[dict]:
    """Google 테이크아웃 '내활동.html'(한국어·영어). 같은 Gemini 대화(app/<ID>)끼리 한 대화로 묶는다."""
    convs: dict[str, dict] = {}
    for block in text.split('<div class="outer-cell')[1:]:
        body_start = block.find("mdl-typography--body-1")
        if body_start < 0:
            continue
        cell = block[block.find(">", body_start) + 1:]
        m = _TK_DATE.search(cell)
        if not m:
            continue
        ts = _parse_takeout_date(m.group(1) or m.group(2))
        if not ts:
            continue
        head = _plain(cell[:m.start()])
        # 프롬프트와 안내 줄(Gem 사용 · 이미지 생성 · 첨부) 나누기
        marker = re.search(r"(항목을 검색함|Prompted|Asked)", head)
        if not marker:
            continue  # 의견 삭제 같은 프롬프트 없는 활동
        prompt = head[:marker.start()].strip()
        if head[:marker.start()].strip() == "" and marker.group(1) in ("Prompted", "Asked"):
            prompt = head[marker.end():].split("\n")[0].strip()
        info = head[marker.end():]
        tags = []
        gem = re.search(r"이 채팅에 (.+?)이?가? 사용되었습니다", info)
        if gem:
            tags.append(f"Gem: {gem.group(1).strip()}")
        img = re.search(r"(이미지|동영상|영상) (\d+)개가 생성", info)
        if img:
            tags.append(f"{img.group(1)} {img.group(2)}개 생성")
        att = re.search(r"파일 (\d+)개 첨부", info)
        if att:
            tags.append(f"첨부 {att.group(1)}개")
        answer_html = cell[m.end():].split('</div><div class="content-cell')[0]
        answer = _plain(answer_html)
        chat = _TK_CHAT.search(block)
        cid = chat.group(1) if chat else ts[:10]
        conv = convs.setdefault(cid, {"source": "gemini", "ext_id": cid, "title": "", "started_at": ts, "messages": []})
        if not prompt and not tags:
            continue
        user_text = (f"({' · '.join(tags)}) " if tags else "") + prompt
        conv["messages"].append({"role": "user", "text": _clean(user_text, names), "ts": ts})
        if answer:
            conv["messages"].append({"role": "assistant", "text": _clean(answer, names, MAX_ASSISTANT), "ts": ts})
        conv["started_at"] = min(conv["started_at"], ts)
    for conv in convs.values():
        conv["messages"].sort(key=lambda x: (x["ts"], x["role"] != "user"))
        first = next((x["text"] for x in conv["messages"] if x["role"] == "user"), "")
        conv["title"] = re.sub(r"^\(.*?\)\s*", "", " ".join(first.split()))[:40] or f"Gemini {conv['started_at'][:10]}"
    return [c for c in convs.values() if c["messages"]]


def _parse_takeout_date(s: str) -> str:
    m = re.search(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.?\s*(오전|오후)?\s*(\d{1,2}):(\d{2})(?::(\d{2}))?", s)
    if m:
        y, mo, d, ampm, h, mi, sec = m.groups()
        h = int(h) % 12 + (12 if ampm == "오후" else 0)
        return datetime(int(y), int(mo), int(d), h, int(mi), int(sec or 0), tzinfo=KST).isoformat()
    for fmt in ("%b %d, %Y, %I:%M:%S %p", "%b %d, %Y, %I:%M:%S %p"):
        try:
            return datetime.strptime(re.sub(r"\s+[A-Z]{2,4}$", "", s), fmt).replace(tzinfo=KST).isoformat()
        except ValueError:
            continue
    return ""


# ---------- claude.ai 내보내기 '목록표(manifest)' ----------
class ManifestError(ValueError):
    """올린 파일이 실제 데이터가 아니라 다운로드 링크 목록일 때. files 에 받아야 할 파일 목록이 있다."""

    NEEDED = {"conversations": "대화 전부 (꼭 필요)", "memories": "Claude가 기억하는 나 (필요)",
              "projects": "프로젝트·올린 파일 (있으면 좋음)"}

    def __init__(self, files: list[dict]):
        self.files = [f for f in files if f.get("category") in self.NEEDED]
        super().__init__("이 파일은 claude.ai 내보내기의 '다운로드 목록표'입니다. 안에 있는 링크로 실제 파일을 받아서 올려 주세요")


# ---------- 파일 → 자동 판별 ----------
def detect_and_parse(filename: str, raw: bytes, names: list[str]) -> tuple[str, list[dict]]:
    """올린 파일(zip/json/html)의 종류를 알아내서 변환. (설명, 대화목록)을 돌려준다."""
    if filename.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            members = z.namelist()
            for target in ("conversations.json", "MyActivity.json", "MyActivity.html", "내활동.json", "내활동.html"):
                hit = next((m for m in members if m.endswith(target) and ("Gemini" in m or "conversations" in target)), None)
                if hit:
                    return detect_and_parse(hit, z.read(hit), names)
            # claude.ai 새 내보내기: conversations-000.zip · memories-000.zip 안의 json/jsonl 여러 개
            base = Path(filename).name.lower()
            if base.startswith("memories"):
                return "Claude 메모리", claude_memories(_zip_texts(z, members), names)
            records = [obj for m in members for obj in _json_objects(z.read(m), m)]
            convs = [r for r in records if isinstance(r, dict) and "chat_messages" in r]
            if convs:
                return "Claude AI (웹·앱)", claude_web(convs, names)
            gpt = [r for r in records if isinstance(r, dict) and "mapping" in r]
            if gpt:
                return "ChatGPT", chatgpt(gpt, names)
            if base.startswith("projects"):
                return "Claude 프로젝트", claude_projects(records, names)
            if base.startswith(("light_metadata", "feedback", "frames")):
                return f"건너뜀({base.split('-')[0]})", []
        raise ValueError("zip 안에서 대화 기록(conversations)이나 Gemini 활동 파일을 찾지 못했습니다")
    text = raw.decode("utf-8-sig")
    if filename.lower().endswith(".html"):
        return "Gemini (HTML)", gemini_html(text, names)
    data = json.loads(text)
    if isinstance(data, dict) and data.get("data_files") and any("export_url" in f for f in data["data_files"]):
        raise ManifestError(data["data_files"])
    if isinstance(data, list) and data:
        first = data[0]
        if "mapping" in first:
            return "ChatGPT", chatgpt(data, names)
        if "chat_messages" in first:
            return "Claude AI (웹·앱)", claude_web(data, names)
        if "title" in first and ("time" in first or "products" in first):
            return "Gemini", gemini(data, names)
    raise ValueError("어떤 서비스의 파일인지 알아내지 못했습니다 (ChatGPT·Claude·Gemini 내보내기 파일인지 확인)")


# ---------- 각 AI가 써 준 '내 사용 보고서' ----------
def self_report(source: str, text: str, names: list[str], received: str | None = None,
                mode: str = "initial") -> list[dict]:
    """프롬프트로 받은 보고서를 '## 제목' 단위로 잘라 한 대화로 저장한다(받은 날 기준)."""
    from core.prompts import PROMPTS, split_report

    when = received or datetime.now(KST).isoformat(timespec="seconds")
    day = when[:10]
    service = PROMPTS[source]["service"]
    msgs = [{"role": "self_report", "text": _clean(f"[{title}] {body}", names), "ts": when}
            for title, body in split_report(text)]
    kind = "초기 전체" if mode == "initial" else "월간"
    return [{"source": source, "ext_id": f"self-report-{mode}-{day}", "title": f"{service}가 쓴 사용 보고서 ({kind}, {day})",
             "started_at": when, "messages": msgs}]


# ---------- GitHub 커밋 ----------
def github(names: list[str], since: str | None = None) -> list[dict]:
    """내 저장소들의 내 커밋(포크 제외). 저장소 하나 = 대화 하나, 커밋 메시지 = 기록."""
    from core.github_activity import _gh, _gh_lines

    login = _gh(["api", "user", "--jq", ".login"]).strip()
    repos = json.loads(_gh(["repo", "list", login, "--limit", "300", "--json", "name,createdAt,isFork,isPrivate"]))
    out = []
    for repo in repos:
        if repo.get("isFork"):
            continue
        query = f"repos/{login}/{repo['name']}/commits?author={login}&per_page=100"
        if since:
            query += f"&since={since}T00:00:00%2B09:00"
        try:
            items = _gh_lines(["api", "--paginate", query, "--jq", ".[] | {m: .commit.message, d: .commit.author.date}"])
        except RuntimeError:
            continue
        title = repo["name"] + (" (비공개)" if repo.get("isPrivate") else "")
        msgs = [{"role": "commit", "text": _clean((c.get("m") or "").splitlines()[0] if c.get("m") else "", names),
                 "ts": _iso(c.get("d"))} for c in items]
        msgs = [m for m in msgs if m["text"] and m["ts"]]
        if msgs:
            out.append({"source": "github", "ext_id": repo["name"], "title": title,
                        "started_at": _iso(repo.get("createdAt")), "messages": msgs})
    return out


def from_folder(folder: str | Path, names: list[str]) -> list[tuple[str, list[dict]]]:
    """압축을 푼 내보내기 폴더에서 아는 파일을 모두 찾아 읽는다. [(파일 설명, 대화목록)]"""
    root = Path(folder)
    if not root.exists():
        raise ValueError(f"폴더가 없습니다: {root}")
    found = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        name = path.name
        gemini_dir = "Gemini" in str(path.parent)
        claude_zip = name.lower().endswith(".zip") and name.lower().startswith(("conversations", "memories", "projects"))
        if claude_zip or name == "conversations.json" or (gemini_dir and name in ("MyActivity.json", "MyActivity.html", "내활동.html", "내활동.json")):
            kind, convs = detect_and_parse(name, path.read_bytes(), names)
            found.append((f"{kind} · {path.relative_to(root)}", convs))
    if not found:
        raise ValueError("이 폴더에서 conversations.json 이나 Gemini 활동 파일(내활동.html·MyActivity)을 찾지 못했습니다")
    return found


# ---------- claude.ai 아티팩트 목록 ----------
def claude_artifacts(items: list[dict], names: list[str]) -> list[dict]:
    """[{title, url, updated}] → 'Claude (웹·앱)'의 아티팩트 기록. 만든 결과물 목록으로 쓴다."""
    msgs = [{"role": "artifact", "text": _clean(f"아티팩트: {it['title']} ({it['url']})", names),
             "ts": _iso(f"{it['updated']}T12:00:00+09:00")} for it in items if it.get("title") and it.get("updated")]
    return [{"source": "claude_web", "ext_id": "artifacts", "title": "claude.ai 아티팩트",
             "started_at": min((m["ts"] for m in msgs), default=""), "messages": msgs}] if msgs else []


def _json_objects(raw: bytes, name: str) -> list:
    """json(목록·객체) 또는 jsonl 파일에서 객체들을 꺼낸다. 못 읽으면 빈 목록."""
    if not name.lower().endswith((".json", ".jsonl")):
        return []
    text = raw.decode("utf-8-sig", errors="ignore").strip()
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("conversations", "items", "data"):
                if isinstance(data.get(key), list):
                    return data[key]
            return [data]
    except json.JSONDecodeError:
        out = []
        for line in text.splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out
    return []


def _zip_texts(z: zipfile.ZipFile, members: list[str]) -> list[str]:
    texts = []
    for m in members:
        if m.lower().endswith((".json", ".jsonl", ".md", ".txt")):
            texts.append(z.read(m).decode("utf-8-sig", errors="ignore"))
    return texts


def claude_memories(texts: list[str], names: list[str]) -> list[dict]:
    """claude.ai 메모리 → 'Claude (웹·앱)' 자기 보고서의 '이 서비스가 기억하는 나' 섹션으로 넣는다."""
    pieces = []
    for t in texts:
        try:
            data = json.loads(t)
        except json.JSONDecodeError:
            pieces.append(t)
            continue

        def walk(x):
            if isinstance(x, str) and len(x.strip()) > 3:
                pieces.append(x.strip())
            elif isinstance(x, dict):
                for k, v in x.items():
                    if k not in ("uuid", "id", "created_at", "updated_at", "account_uuid"):
                        walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)
        walk(data)
    body = "\n".join(dict.fromkeys(pieces)).strip()
    if not body:
        return []
    when = datetime.now(KST).isoformat(timespec="seconds")
    # '**Work context**' 같은 굵은 제목 단위로 나눠 섹션마다 따로 저장 (검색·근거가 정확해짐)
    chunks, title, buf = [], "메모리", []
    for line in body.splitlines():
        head = re.fullmatch(r"\s*\*\*(.+?)\*\*\s*", line)
        if head:
            if "".join(buf).strip():
                chunks.append((title, "\n".join(buf).strip()))
            title, buf = head.group(1).strip(), []
        else:
            buf.append(line)
    if "".join(buf).strip():
        chunks.append((title, "\n".join(buf).strip()))
    msgs = [{"role": "self_report", "text": _clean(f"[이 서비스가 기억하는 나 · {t}] {b}", names)[:6000], "ts": when}
            for t, b in chunks]
    return [{"source": "claude_web", "ext_id": "memories", "title": "claude.ai 메모리 (내보내기)", "started_at": when,
             "messages": msgs}]


def claude_projects(objs: list[dict], names: list[str]) -> list[dict]:
    """claude.ai 프로젝트: 이름·설명·내가 쓴 지침(앞부분)·올린 문서 이름을 '아티팩트' 기록으로."""
    msgs = []
    for p in objs:
        if not isinstance(p, dict) or p.get("is_starter_project"):
            continue
        docs = ", ".join(d.get("filename", "") for d in p.get("docs", [])[:10])
        guide = " ".join((p.get("prompt_template") or "").split())[:600]
        text = (f"프로젝트: {p.get('name', '')} — {(p.get('description') or '').strip()}"
                + (f" / 지침: {guide}" if guide else "") + (f" / 문서: {docs}" if docs else ""))
        ts = _iso(p.get("created_at"))
        if ts:
            msgs.append({"role": "artifact", "text": _clean(text, names), "ts": ts})
    return [{"source": "claude_web", "ext_id": "projects", "title": "claude.ai 프로젝트",
             "started_at": min((m["ts"] for m in msgs), default=""), "messages": msgs}] if msgs else []
