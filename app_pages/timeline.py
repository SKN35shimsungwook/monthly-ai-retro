import pandas as pd
import streamlit as st

from core import stats
from core.analysis import check_goals, load_me
from core.metrics import METRIC_BY_KEY, METRICS, fmt
from core.ui import load_reports, report_title

reports, is_sample = load_reports()

st.title("타임라인")
st.caption("리포트가 쌓일수록 내가 어떻게 바뀌는지 보여줍니다.")

# ---- 서비스별 사용량 ----
activity = pd.DataFrame(stats.monthly_activity())
if not activity.empty:
    with st.container(border=True):
        st.markdown("**월별 AI 사용량** (서비스별 내 메시지 수)")
        st.bar_chart(activity, x="월", y="메시지", color="출처", height=260)

# ---- 추이 (기준선의 월별 숫자 + 이후 월간 리포트) ----
rows = []
for r in reports:
    for m in r.get("monthly", []):  # 초기 총정리에 담긴 달별 숫자로 처음부터 그린다
        for k, v in (m.get("metrics") or {}).items():
            if v is not None and k in METRIC_BY_KEY:
                rows.append({"리포트": m["month"], "순서": m["month"], "지표": METRIC_BY_KEY[k].label, "값": v})
for r in reports:
    if r.get("monthly"):
        continue
    for k, v in (r.get("metrics") or {}).items():
        if v is not None and k in METRIC_BY_KEY:
            rows.append({"리포트": r["period"]["since"][:7], "순서": r["period"]["since"], "지표": METRIC_BY_KEY[k].label, "값": v})
with st.container(border=True):
    st.markdown("**지표 추이**")
    if len({x["순서"] for x in rows}) < 2:
        st.caption("기준선(초기 총정리)을 에이전트로 만들면 처음 달부터 선 그래프가 그려집니다.")
    rate_keys = [m.key for m in METRICS if m.kind == "rate"]
    picked = st.pills("보고 싶은 지표", [METRIC_BY_KEY[k].label for k in rate_keys], selection_mode="multi",
                      default=[METRIC_BY_KEY[k].label for k in ("criteria_rate", "evidence_rate", "why_rate")])
    df = pd.DataFrame(rows)
    if not df.empty and picked:
        df = df[df["지표"].isin(picked)].sort_values("순서")
        st.line_chart(df, x="리포트", y="값", color="지표", height=280, y_label="%")

# ---- 리포트 카드 (최신 먼저) ----
st.subheader("리포트", divider="violet")
for idx in range(len(reports) - 1, -1, -1):
    r = reports[idx]
    me = {"reactions": {}, "goals": []} if is_sample else load_me(r["label"])
    prev_me = None if (is_sample or idx == 0) else load_me(reports[idx - 1]["label"])
    with st.container(border=True):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown(f"### {report_title(r)}")
            st.caption(f"{r['period']['since']} ~ {r['period']['until']}")
        st.markdown(r["headline"])
        a, b, c = st.columns(3)
        a.caption("사용 유형")
        a.markdown(r["summary"]["type"])
        ups = sum(1 for v in me.get("reactions", {}).values() if v == 1)
        downs = sum(1 for v in me.get("reactions", {}).values() if v == 0)
        b.caption("내 반응")
        b.markdown(f":material/thumb_up: {ups}  ·  :material/thumb_down: {downs}")
        c.caption("고른 목표")
        c.markdown("\n".join(f"- {g['text']}" for g in me.get("goals", [])) or "아직 없음")
        for g in check_goals(prev_me, r):
            mark = {True: ":green-badge[달성]", False: ":red-badge[미달성]", None: ":gray-badge[확인 불가]"}[g["achieved"]]
            st.markdown(f"{mark} 지난 목표 · {g['text']} → {fmt(g['metric'], g['value'])}")
        if st.button("리포트 열기", key=f"open_{r['label']}", icon=":material/open_in_new:"):
            st.session_state.report_label = r["label"]
            st.switch_page("app_pages/report.py")
