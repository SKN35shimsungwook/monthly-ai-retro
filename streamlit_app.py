import streamlit as st

from core.analysis import list_reports

st.set_page_config(page_title="AI 활용 회고", page_icon=":material/self_improvement:", layout="wide",
                   initial_sidebar_state="collapsed")

st.session_state.setdefault("report_label", None)  # 리포트 화면에서 열 리포트
st.session_state.setdefault("build_step", None)    # 만들기 화면의 현재 단계

# 작업 순서대로: 만들기 → 리포트 → 타임라인 → 묻기. 리포트가 아직 없으면 '만들기'부터 연다.
has_reports = bool(list_reports())
page = st.navigation(
    [
        st.Page("app_pages/data.py", title="1 만들기", icon=":material/construction:", default=not has_reports),
        st.Page("app_pages/report.py", title="2 리포트", icon=":material/article:", default=has_reports),
        st.Page("app_pages/timeline.py", title="3 타임라인", icon=":material/timeline:"),
        st.Page("app_pages/ask.py", title="4 묻기", icon=":material/forum:"),
        st.Page("app_pages/howto.py", title="도움말", icon=":material/help:"),
    ],
    position="top",
)
page.run()
