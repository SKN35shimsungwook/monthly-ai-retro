import streamlit as st

from core.analysis import PERSON_PARTS, SECTIONS, check_goals, load_me, save_me, to_markdown
from core.metrics import GROUPS, METRIC_BY_KEY, METRICS, fmt
from core.store import SOURCES
from core.ui import load_reports, report_title, show_evidence

reports, is_sample = load_reports()
labels = [r["label"] for r in reports]
by_label = {r["label"]: r for r in reports}

# ---- 맨 위 한 줄: 리포트 고르기 · 내려받기 (사이드바 없이) ----
if st.session_state.report_label not in by_label:
    st.session_state.report_label = labels[-1]
with st.container(horizontal=True, vertical_alignment="bottom"):
    label = st.selectbox("리포트", labels, key="report_label", format_func=lambda x: report_title(by_label[x]),
                         width=320)
    data = by_label[label]
    st.caption(f"{data['period']['since']} ~ {data['period']['until']} · 작성 {data.get('author', '')}")
    download_slot = st.empty()

# ---- 목차 (가로 한 줄, 누르면 그 섹션으로 이동) ----
toc = [(title, anchor) for key, title, anchor in SECTIONS
       if key not in ("change", "tools", "monthly", "research") or data.get(key)] + [("다음 목표", "goals")]
st.markdown(" · ".join(f"[{title}](#{anchor})" for title, anchor in toc))

me = {"reactions": {}, "goals": [], "note": ""} if is_sample else load_me(label)
docs = data.get("evidence_docs", {})
idx = labels.index(label)
prev_me = None if (is_sample or idx == 0) else load_me(labels[idx - 1])


def remember() -> None:
    """반응·목표·메모를 바꿀 때마다 바로 파일에 저장(샘플은 저장하지 않음)."""
    if is_sample:
        return
    m = {"reactions": {}, "goals": [], "note": st.session_state.get(f"note_{label}", "")}
    for k, v in st.session_state.items():
        if isinstance(k, str) and k.startswith(f"fb_{label}_") and v is not None:
            m["reactions"][k[len(f"fb_{label}_"):]] = v
    picked = st.session_state.get(f"goals_{label}") or []
    m["goals"] = [g for g in data["goal_candidates"] if g["text"] in picked]
    save_me(label, m)


def feedback(item_key: str) -> None:
    st.feedback("thumbs", key=f"fb_{label}_{item_key}", default=me["reactions"].get(item_key),
                on_change=remember)


if is_sample:
    st.info("가상의 사용자 샘플 리포트입니다. 내 리포트는 '1 만들기'에서 만들면 여기에 나타납니다.",
            icon=":material/info:")

# ---- 머리말 ----
with st.container(horizontal=True, vertical_alignment="center"):
    st.title(f"{report_title(data)} 리포트")
    st.badge(data.get("kind", ""), icon=":material/date_range:", color="violet")
with st.container(border=True):
    st.markdown(f"#### {data['headline']}")
    if data.get("sources"):
        st.caption("분석한 기록: " + " · ".join(f"{SOURCES.get(k, (k,))[0]} {v:,}개" for k, v in data["sources"].items()))

t = data.get("totals", {})
if t:
    with st.container(horizontal=True):
        for name, value in (("Claude 세션", t.get("sessions")), ("내 메시지", t.get("user_messages")),
                            ("활동한 날", t.get("active_days")), ("GitHub 커밋", t.get("commits")),
                            ("새 저장소", t.get("new_repos")), ("주간회고", t.get("blog_posts"))):
            if value is not None:
                st.metric(name, f"{value:,}", border=True)

st.caption("각 항목 아래 👍/👎를 누르면 바로 저장됩니다. 👎 한 항목은 블로그용 글에서 빠집니다. 따로 쓸 것은 없습니다.")

# ---- 요약 ----
s = data["summary"]
st.header("요약", anchor="summary", divider="violet")
c1, c2, c3 = st.columns([1, 1.2, 1.2])
with c1.container(border=True, height="stretch"):
    st.markdown(":material/person: **사용 유형**")
    st.markdown(s["type"])
with c2.container(border=True, height="stretch"):
    st.markdown(":green[:material/thumb_up: **핵심 강점**]")
    st.markdown("\n".join(f"{i}. {x}" for i, x in enumerate(s["strengths_top"], 1)))
with c3.container(border=True, height="stretch"):
    st.markdown(":orange[:material/warning: **핵심 약점**]")
    st.markdown("\n".join(f"{i}. {x}" for i, x in enumerate(s["weaknesses_top"], 1)))
st.success(f"**먼저 할 일** · {s['first_action']}", icon=":material/flag:")

# ---- 월별 흐름 (기준선) ----
if data.get("monthly"):
    import pandas as pd

    st.header("월별 흐름", anchor="monthly", divider="violet")
    st.caption("처음 달부터 달마다의 숫자와 흐름입니다. 이후 월간 리포트는 이 기준선과 비교됩니다.")
    flow = pd.DataFrame([{"달": m["month"], "끝난 기준(%)": m["metrics"].get("criteria_rate"),
                          "증거 요구(%)": m["metrics"].get("evidence_rate"), "설명 요청(%)": m["metrics"].get("why_rate"),
                          "계획 먼저(%)": m["metrics"].get("plan_first_rate")} for m in data["monthly"]])
    st.line_chart(flow, x="달", height=240, y_label="%")
    for m in data["monthly"]:
        t = m.get("totals", {})
        with st.container(border=True):
            with st.container(horizontal=True, vertical_alignment="center"):
                st.markdown(f"**{m['month']}**")
                st.caption(f"메시지 {t.get('user_messages', 0):,} · 세션 {t.get('sessions', 0)} · 커밋 {t.get('commits', 0):,}")
            st.markdown(m.get("summary", ""))
            if m.get("highlight"):
                st.caption(f":material/star: {m['highlight']}")

# ---- 사용 유형과 방식 ----
u = data["usage"]
st.header("사용 유형과 방식", anchor="usage", divider="violet")
st.markdown(u["overview"])
cols = st.columns(3)
for i, m in enumerate(u.get("made", [])):
    with cols[i % 3].container(border=True, height="stretch"):
        st.markdown(f"**{m['category']}**")
        st.markdown(m["examples"])
        st.caption(m.get("note", ""))
left, right = st.columns(2)
with left.container(border=True, height="stretch"):
    st.markdown(":material/route: **일을 시키는 흐름**")
    st.markdown("\n".join(f"{i}. {x}" for i, x in enumerate(u.get("how", []), 1)))
with right.container(border=True, height="stretch"):
    st.markdown(":material/repeat: **눈에 띄는 습관**")
    st.markdown("\n".join(f"- {x}" for x in u.get("habits", [])))


# ---- AI를 잘 쓰는 사람들의 특징 (조사) ----
if data.get("research"):
    rs = data["research"]
    st.header("AI를 잘 쓰는 사람들의 특징", anchor="research", divider="blue")
    st.caption("웹에서 찾은 연구·공식 가이드입니다. 아래 강점·약점은 이 기준과 비교해 읽으면 됩니다.")
    if not rs.get("studies") and not rs.get("traits"):
        st.info("출처 없음: 웹 검색에서 확인된 출처가 없어 이 섹션을 비워 두었습니다.", icon=":material/link_off:")
    for it in rs.get("studies", []):
        with st.container(border=True):
            st.markdown(f"**{it.get('name', '')}**")
            st.markdown(it.get("finding", ""))
            with st.container(horizontal=True):
                for j, link in enumerate(it.get("links", [])[:2]):
                    st.link_button(link.get("title") or f"출처 {j + 1}", link["uri"], icon=":material/open_in_new:")
    if rs.get("traits"):
        st.markdown("**잘 쓰는 사람들의 특징**")
    grid = st.columns(2)
    for i, t in enumerate(rs.get("traits", [])):
        with grid[i % 2].container(border=True, height="stretch"):
            st.markdown(f"**{i + 1}. {t.get('trait', '')}**")
            st.markdown(t.get("how", ""))
            links = t.get("links", [])
            if links:
                st.caption("출처: " + " · ".join(f"[{l.get('title') or '링크'}]({l['uri']})" for l in links[:2]))

# ---- 강점 · 약점 ----
def cards(key: str, color: str) -> None:
    items = data[key]
    grid = st.columns(2)
    for i, it in enumerate(items):
        with grid[i % 2].container(border=True, height="stretch"):
            with st.container(horizontal=True, vertical_alignment="center"):
                st.markdown(f"**{it['title']}**")
                if it.get("d4"):
                    st.badge(it["d4"], color=color)
            st.markdown(it["why"])
            st.caption(f":material/format_quote: {it['evidence']}")
            with st.container(horizontal=True, vertical_alignment="center"):
                feedback(f"{key}.{i}")
                show_evidence(it["evidence"], docs)


st.header("강점", anchor="strengths", divider="green")
cards("strengths", "green")
st.header("약점", anchor="weaknesses", divider="orange")
cards("weaknesses", "orange")

# ---- 보완점 ----
st.header("보완점과 추천", anchor="recommendations", divider="blue")
st.caption("'이렇게' 칸은 그대로 복사해서 Claude에게 보낼 수 있습니다 (오른쪽 위 복사 버튼).")
for i, r in enumerate(sorted(data["recommendations"], key=lambda r: r.get("priority", 99))):
    with st.container(border=True):
        st.markdown(f"**{r.get('priority', i + 1)}. {r['title']}**")
        a, b = st.columns([1, 2])
        a.caption("지금")
        a.markdown(r["now"])
        b.caption("이렇게")
        b.code(r["better"].strip('"'), language=None, wrap_lines=True)
        with st.container(horizontal=True, vertical_alignment="center"):
            feedback(f"recommendations.{i}")
            show_evidence(r["now"], docs)

# ---- 변화 ----
if data.get("change"):
    st.header("지난 기간 대비 변화", anchor="change", divider="violet")
    if data.get("kind") == "초기 총정리":
        st.caption("첫 리포트라 기간 안에서 초반과 최근을 비교했습니다. 다음 달부터는 지난달과 비교합니다.")
    color = {"좋아짐": "green", "그대로": "gray", "나빠짐": "red"}
    for ch in data["change"]:
        with st.container(border=True):
            with st.container(horizontal=True, vertical_alignment="center"):
                st.markdown(f"**{ch['item']}**")
                st.badge(ch["verdict"], color=color.get(ch["verdict"], "gray"))
            a, mid, b = st.columns([10, 1, 10], vertical_alignment="center")
            a.markdown(ch["before"])
            mid.markdown(":material/arrow_forward:")
            b.markdown(ch["after"])

# ---- 나라는 사람 ----
st.header("나라는 사람", anchor="person", divider="violet")
tabs = st.tabs([name for _key, name in PERSON_PARTS])
for tab, (key, _name) in zip(tabs, PERSON_PARTS):
    with tab:
        for line in data["person"].get(key, []):
            st.markdown(f"- {line}")
        with st.container(horizontal=True, vertical_alignment="center"):
            feedback(f"person.{key}")
            show_evidence(" ".join(data["person"].get(key, [])), docs)

# ---- 연계 추천 ----
if data.get("tools"):
    st.header("연계 추천", anchor="tools", divider="blue")
    st.caption("지금 쓰는 도구와 결합하면 시너지가 나는 새 기술·플러그인·스킬입니다. 추천마다 실제 검색한 출처가 붙어 있습니다.")
    effort_color = {"낮음": "green", "중간": "orange", "높음": "red"}
    grid = st.columns(2)
    for i, t in enumerate(data["tools"]):
        with grid[i % 2].container(border=True, height="stretch"):
            with st.container(horizontal=True, vertical_alignment="center"):
                st.markdown(f"**{t['name']}**")
                st.badge(t.get("kind", ""), color="blue")
                if t.get("effort"):
                    st.badge(f"난이도 {t['effort']}", color=effort_color.get(t["effort"], "gray"))
            st.markdown(t.get("what", ""))
            st.markdown(f":material/join_inner: **시너지** · {t.get('synergy', '')}")
            if t.get("for_weakness"):
                st.caption(f"해결하는 약점: {t['for_weakness']}")
            st.markdown(f":material/play_arrow: **첫 단계** · {t.get('first_step', '')}")
            with st.container(horizontal=True, vertical_alignment="center"):
                feedback(f"tools.{i}")
                for j, link in enumerate(t.get("links", [])[:3]):
                    st.link_button(link.get("title") or f"출처 {j + 1}", link["uri"], icon=":material/open_in_new:")

# ---- 지표 상세 ----
metrics = data.get("metrics", {})
if metrics:
    with st.expander("지표 15개 자세히 보기", icon=":material/monitoring:"):
        st.caption("키워드 규칙으로 센 값이라 방향을 보는 용도입니다.")
        for group in GROUPS:
            st.markdown(f"**{group}**")
            with st.container(horizontal=True):
                for m in [m for m in METRICS if m.group == group]:
                    st.metric(m.label, fmt(m.key, metrics.get(m.key)), border=True, help=m.desc)

# ---- 목표 ----
st.header("다음 목표", anchor="goals", divider="violet")
checks = check_goals(prev_me, data)
if checks:
    st.markdown("**지난 목표는 지켰나**")
    with st.container(horizontal=True):
        for g in checks:
            mark = {True: ":green-badge[달성]", False: ":red-badge[미달성]", None: ":gray-badge[확인 불가]"}[g["achieved"]]
            with st.container(border=True):
                st.markdown(f"{mark} {g['text']}")
                st.caption(f"이번 값: {fmt(g['metric'], g['value'])}")
st.pills("다음 기간 목표를 골라 주세요 (최대 2개, 다음 리포트에서 자동 확인)",
         [g["text"] for g in data["goal_candidates"]], selection_mode="multi",
         default=[g["text"] for g in me.get("goals", [])], key=f"goals_{label}", on_change=remember)
if len(st.session_state.get(f"goals_{label}") or []) > 2:
    st.warning("목표는 2개까지만 고르는 걸 추천합니다.", icon=":material/warning:")
st.text_input("한 줄 남기기 (선택)", value=me.get("note", ""), key=f"note_{label}", on_change=remember,
              placeholder="예: 다음 달엔 요청할 때 끝난 기준부터 쓰자")

# 맨 위 줄에 내려받기 버튼 (반응·목표가 반영된 최신 내용으로)
download_slot.download_button("블로그용 글 (.md)", to_markdown(data, load_me(label) if not is_sample else me),
                              file_name=f"{label}.md", mime="text/markdown", icon=":material/download:")

if data.get("limits"):
    st.divider()
    st.caption("이 분석의 한계")
    st.caption("\n".join(f"- {x}" for x in data["limits"]))
