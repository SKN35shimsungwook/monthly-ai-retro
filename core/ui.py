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


def api_key() -> str:
    """secrets → 환경변수 → 이 화면에서 입력한 값(세션에만, 파일에 안 남김)."""
    try:
        key = st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        key = ""
    return key or os.environ.get("GEMINI_API_KEY", "") or st.session_state.get("api_key", "")


def key_input() -> str:
    key = api_key()
    if not key:
        st.text_input("Gemini API 키", type="password", key="api_key",
                      help="이 브라우저 세션에서만 쓰고 파일에 저장하지 않습니다. "
                           ".streamlit/secrets.toml 에 GEMINI_API_KEY 로 넣어 두면 매번 안 넣어도 됩니다.")
        key = st.session_state.get("api_key", "")
    return key


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
