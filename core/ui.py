"""여러 화면에서 같이 쓰는 함수."""
import json
import os
import re
from pathlib import Path

import streamlit as st

from core.analysis import list_reports

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample" / "sample.analysis.json"
CONFIG = ROOT / "config.local.json"
_ID = re.compile(r"\[([A-Z]-\d+)\]")


def report_title(data: dict) -> str:
    if data.get("kind") == "초기 총정리":
        suffix = " (에이전트)" if "에이전트" in data.get("author", "") else ""
        return f"0회차 초기 총정리{suffix}"
    if data.get("kind") == "기간":
        return f"{data['period']['since']} ~ {data['period']['until']}"
    since = data["period"]["since"]
    return f"{since[:4]}년 {int(since[5:7])}월"


@st.cache_data(ttl=30)
def load_reports() -> tuple[list[dict], bool]:
    """(리포트 목록, 샘플인지). 내 리포트가 없으면(배포판) 샘플을 보여준다."""
    reports = list_reports()
    if reports:
        return reports, False
    return [json.loads(SAMPLE.read_text(encoding="utf-8"))], True


def config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}


SECRETS = ROOT / ".streamlit" / "secrets.toml"


KEYS = {"gemini": ("GEMINI_API_KEY", "Gemini", "AIza… 로 시작하는 키", "Google AI Studio"),
        "openai": ("OPENAI_API_KEY", "ChatGPT", "sk-… 로 시작하는 키", "platform.openai.com 의 API keys")}


def _key_from_file(name: str) -> str:
    """앱을 다시 켜지 않아도 방금 저장한 키를 읽을 수 있게 파일에서 직접 읽는다."""
    if not SECRETS.exists():
        return ""
    m = re.search(rf'^\s*{name}\s*=\s*"([^"]*)"', SECRETS.read_text(encoding="utf-8"), re.M)
    return m.group(1).strip() if m else ""


def api_key(provider: str = "gemini") -> str:
    """이번 세션에 넣은 키 → .streamlit/secrets.toml → 환경변수 순서."""
    name = KEYS[provider][0]
    return st.session_state.get(f"api_key_{provider}", "") or _key_from_file(name) or os.environ.get(name, "")


def save_key(key: str, provider: str = "gemini") -> None:
    """키를 .streamlit/secrets.toml 에 저장(있으면 바꿈). 이 파일은 GitHub에 올라가지 않는다."""
    name = KEYS[provider][0]
    SECRETS.parent.mkdir(parents=True, exist_ok=True)
    text = SECRETS.read_text(encoding="utf-8") if SECRETS.exists() else ""
    line = f'{name} = "{key}"'
    if re.search(rf"^\s*{name}\s*=", text, re.M):
        text = re.sub(rf"^\s*{name}\s*=.*$", lambda _m: line, text, flags=re.M)
    else:
        text += ("\n" if text and not text.endswith("\n") else "") + line + "\n"
    SECRETS.write_text(text, encoding="utf-8")


def check_key(key: str, provider: str = "gemini") -> str | None:
    """키가 실제로 작동하는지 가볍게 확인. 문제가 있으면 이유를 돌려준다."""
    where = KEYS[provider][3]
    try:
        if provider == "openai":
            from openai import OpenAI

            client = OpenAI(api_key=key, max_retries=0, timeout=20)
            next(iter(client.models.list()), None)
            return None
        from google import genai

        client = genai.Client(api_key=key)  # 변수로 붙잡아 둬야 확인이 끝나기 전에 연결이 닫히지 않음
        pager = client.models.list(config={"page_size": 1})
        next(iter(pager), None)
        return None
    except Exception as exc:  # 잘못된 키·네트워크 오류
        msg = str(exc)
        if any(w in msg for w in ("API_KEY_INVALID", "API key not valid", "invalid_api_key", "Incorrect API key", "400", "401")):
            return f"키가 맞지 않아요. {where}에서 복사한 키 전체를 다시 넣어 주세요."
        return f"키를 확인하지 못했어요: {msg[:120]}"


def key_input(provider: str = "gemini") -> str:
    """키가 있으면 '연결됨'만 보여 주고, 없으면 입력칸 + '키 적용' 버튼 (엔터를 누르지 않아도 됨)."""
    _, name, hint, _ = KEYS[provider]
    editing = f"key_editing_{provider}"
    key = api_key(provider)
    if key:
        with st.container(horizontal=True, vertical_alignment="center"):
            st.badge(f"{name} 키 연결됨", icon=":material/key:", color="green")
            if st.button("키 바꾸기", key=f"key_change_{provider}", type="tertiary"):
                st.session_state[f"api_key_{provider}"] = ""
                st.session_state[editing] = True
                st.rerun()
        if not st.session_state.get(editing):
            return key
    with st.form(f"key_form_{provider}", border=False, clear_on_submit=True):
        value = st.text_input(f"{name} API 키", type="password", placeholder=f"{hint} 붙여넣기")
        remember = st.checkbox("이 PC에 저장 (다음부터 안 넣어도 됨 · GitHub에는 안 올라감)", value=True)
        applied = st.form_submit_button("키 적용", icon=":material/key:", type="primary")
    if applied:
        value = value.strip().strip('"')
        if not value:
            st.warning("키를 붙여넣은 뒤 '키 적용'을 눌러 주세요.", icon=":material/warning:")
            return ""
        with st.spinner("키 확인 중…"):
            problem = check_key(value, provider)
        if problem:
            st.error(problem, icon=":material/error:")
            return ""
        st.session_state[f"api_key_{provider}"] = value
        st.session_state[editing] = False
        if remember:
            save_key(value, provider)
        st.rerun()
    return ""


def cited_ids(text: str) -> list[str]:
    return list(dict.fromkeys(_ID.findall(text)))


def show_evidence(text: str, docs: dict) -> None:
    """문장 속 [C-123] 근거의 원문을 펼쳐 볼 수 있게."""
    ids = [i for i in cited_ids(text) if i in docs]
    if not ids:
        return
    with st.popover(f"근거 원문 {len(ids)}개", icon=":material/description:"):
        for i in ids:
            d = docs[i]
            st.caption(f"**{i}** · {d['source']} · {d['ts'].replace('T', ' ')} · {d['title']}")
            st.markdown(f"> {d['text'][:400]}")
