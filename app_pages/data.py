import calendar
import re
from datetime import date

import streamlit as st

from core import agent, importers, inventory, profile, search, store
from core.analysis import list_reports, load_me
from core.claude_logs import DEFAULT_ROOT
from core.llm import DEFAULT_MODEL, get_llm
from core.prompts import MODES, PROMPTS, emptiness, prompt_for, split_report
from core.recommend import gemini_web_search
from core.ui import config, key_input, load_reports

cfg = config()
names = cfg.get("redact_names", [])
reports = list_reports()
# 모든 서비스를 합친 에이전트 초기 총정리가 기준선 (Claude Code만 본 0회차와 구분)
has_initial = any(r.get("kind") == "초기 총정리" and "에이전트" in r.get("author", "") for r in reports)
over = {r["source"]: r for r in store.overview()}
prof = profile.load()

st.title("만들기")
st.caption("기록을 모으고 AI 컨설턴트에게 리포트를 맡깁니다. 모든 기록은 민감정보를 가린 뒤 이 PC(data/db)에만 저장됩니다.")

# ---- 지금 모인 기록 (항상 보임) ----
with st.container(horizontal=True):
    for src, (name, _l) in store.SOURCES.items():
        r = over.get(src, {})
        n = (r.get("user_msgs") or 0) + (r.get("commits") or 0)
        unit = "커밋" if src == "github" else "메시지"
        st.metric(name, f"{n:,}" if n else "-", border=True,
                  delta="보고서 받음" if r.get("report_parts") else None, delta_color="off",
                  help=f"{unit} 수" + (f" · {(r.get('first') or '')[:10]} ~ {(r.get('last') or '')[:10]}" if r.get("first") else ""))

# ---- 단계 ----
STEPS = ["0 사용 실태", "1 AI 보고서 받기", "2 자동 가져오기", "3 리포트 만들기"]
if st.session_state.build_step not in STEPS:
    has_reports_in = any(r.get("report_parts") for r in over.values())
    st.session_state.build_step = (STEPS[0] if not prof else STEPS[1] if not has_reports_in
                                   else STEPS[2] if "claude_code" not in over else STEPS[3])


def go_step(step: str) -> None:
    st.session_state.build_step = step


st.segmented_control("단계", STEPS, key="build_step", label_visibility="collapsed", width="stretch")
step = st.session_state.build_step
st.divider()

# ================= 0. 사용 실태 =================
if step == STEPS[0]:
    st.subheader("어떤 AI를 무엇에, 얼마나 자주 쓰나요?")
    st.caption("이 답에 맞춰 다음 단계의 서비스별 프롬프트가 만들어집니다. 쓰는 방식이 바뀌면 언제든 다시 고르세요.")
    order_names = {s: profile._name(s) for s in profile.RANK_SOURCES}
    ranking = st.multiselect("자주 쓰는 순서대로 고르기", profile.RANK_SOURCES, format_func=order_names.get,
                             default=(prof or {}).get("ranking", profile.RANK_SOURCES))
    uses = {}
    cols = st.columns(3)
    for col, src in zip(cols, ("chatgpt", "gemini", "claude_web")):
        with col.container(border=True, height="stretch"):
            st.markdown(f"**{PROMPTS[src]['service']}**의 주 용도")
            uses[src] = st.pills(f"{src} 용도", list(profile.USES), selection_mode="multi",
                                 format_func=lambda u: profile.USES[u][0], label_visibility="collapsed",
                                 default=(prof or {}).get("uses", {}).get(src, profile.DEFAULT_USES[src]), key=f"use_{src}")
    with st.expander("Claude Code 기록에서 찾은 단서", icon=":material/search:"):
        rows = store.messages(role="user", sources=["claude_code"])
        for name, pat in (("ChatGPT", r"지피티|GPT|chatgpt|ChatGPT|openai|OpenAI"),
                          ("Gemini", r"재미나이|제미나이|gemini|Gemini|나노 ?바나나|딥리서치|딥 리서치|share\.gemini"),
                          ("Claude AI (웹·앱)", r"claude\.ai|아티팩트|artifact")):
            hits = [r for r in rows if re.search(pat, r["text"]) and "<pasted_content" not in r["text"]]
            st.markdown(f"**{name}** 언급 {len(hits)}개")
            for r in hits[-3:]:
                st.caption(f"{r['ts'][:10]} · {' '.join(r['text'].split())[:90]}")
    with st.container(horizontal=True):
        if st.button("저장", type="primary", icon=":material/save:", disabled=len(ranking) < 2):
            prof = profile.save(ranking, {k: v or [] for k, v in uses.items()}, note=(prof or {}).get("note", ""))
            st.toast("사용 실태를 저장했습니다", icon=":material/check:")
        st.button("다음: AI 보고서 받기", icon=":material/arrow_forward:", on_click=go_step, args=(STEPS[1],))

# ================= 1. AI 보고서 받기 =================
elif step == STEPS[1]:
    today_ = date.today()
    last_month = f"{today_.year}-{today_.month - 1:02d}" if today_.month > 1 else f"{today_.year - 1}-12"
    with st.container(horizontal=True, vertical_alignment="center"):
        st.subheader("각 AI에게 '내 사용 보고서' 받기")
        pmode = st.segmented_control("종류", ["initial", "monthly"], format_func=lambda m: MODES[m]["label"],
                                     default="monthly" if has_initial else "initial", key="prompt_mode",
                                     label_visibility="collapsed")
    pmode = pmode or "initial"
    st.caption(("처음 한 번: 각 AI가 처음 쓴 날부터 오늘까지 전부 조사합니다. 이 보고서들이 기준선(0회차)의 재료가 됩니다."
                if pmode == "initial" else f"{last_month} 한 달만 조사합니다. 분기에 한 번 정도면 충분합니다.")
               + (" 프롬프트는 '0 사용 실태'에 맞춰 서비스마다 다르게 만들어졌습니다." if prof else
                  " :orange['0 사용 실태'를 먼저 하면 내 용도에 맞춘 프롬프트가 나옵니다.]"))
    # 네 서비스를 자주 쓰는 순서대로 나란히 (Claude Code도 따로 한 칸)
    order = [s for s in (prof or {}).get("ranking", []) if s in PROMPTS or s == "claude_code"] \
        or ["claude_code", "chatgpt", "gemini", "claude_web"]
    if "claude_code" not in order:
        order.insert(0, "claude_code")

    def tab_label(s: str) -> str:
        r = over.get(s, {})
        done = r.get("user_msgs") if s == "claude_code" else (r.get("report_parts") or r.get("user_msgs"))
        return store.SOURCES[s][0] + (" ✓" if done else "")

    tabs = st.tabs([tab_label(s) for s in order])
    for tab, src in zip(tabs, order):
        if src == "claude_code":
            with tab:
                r_cc = over.get("claude_code", {})
                with st.container(horizontal=True):
                    st.badge("자동 수집", color="blue", icon=":material/sync:")
                    st.badge(f"대화 원문 {r_cc.get('user_msgs') or 0:,}개 · 세션 {r_cc.get('convs') or 0}개"
                             + (f" · {r_cc['first'][:10]} ~ {r_cc['last'][:10]}" if r_cc.get("first") else ""),
                             color="green" if r_cc.get("user_msgs") else "gray")
                    has_cc_report = any(r.get("author") == "Claude Code" for r in reports)
                    st.badge("Claude가 쓴 0회차 리포트 있음" if has_cc_report else "Claude 리포트 아직",
                             color="green" if has_cc_report else "gray")
                st.markdown("**Claude Code는 프롬프트도 내보내기 파일도 필요 없어요.** 이 PC의 `.claude` 폴더에 대화가 그대로 남아 있어서 "
                            "버튼 한 번으로 모입니다. 지금 이 대화처럼 파일을 직접 만들고 실행하는 **개발용 Claude**의 기록이에요.")
                st.caption("Claude AI(웹·앱)와는 다른 기록입니다. claude.ai 대화는 옆의 'Claude AI (웹·앱)' 탭에서 넣어요.")
                if st.button("Claude Code 기록 지금 가져오기", key="cc_tab", type="primary", icon=":material/sync:"):
                    with st.spinner("읽는 중…"):
                        res = store.save_conversations(importers.claude_code(DEFAULT_ROOT, names))
                        search.build()
                    st.success(f"새 메시지 {res['messages']}개를 넣었습니다", icon=":material/check:")
            continue
        p = PROMPTS[src]
        with tab:
            r_now = over.get(src, {})
            with st.container(horizontal=True):
                # 프롬프트로 받은 '사용 보고서'와 내보내기 파일의 '메모리'를 따로 표시
                titles = {m["title"] for m in store.messages(role="self_report", sources=[src])}
                has_prompt = any("사용 보고서" in t for t in titles)
                has_memory = any("메모리" in t for t in titles)
                st.badge("사용 보고서 받음" if has_prompt else "사용 보고서 아직", color="green" if has_prompt else "gray")
                if has_memory:
                    st.badge("메모리 받음", color="green")
                st.badge(f"대화 원문 {r_now.get('user_msgs') or 0:,}개" + (f" · {r_now['first'][:7]}부터" if r_now.get("first") else ""),
                         color="green" if r_now.get("user_msgs") else "gray")
            st.markdown(f"**A. 사용 보고서** — ① 프롬프트 복사 → ② {p['service']} 새 채팅에 붙여넣기 → ③ 받은 답을 붙여넣고 저장")
            st.info(p["before"], icon=":material/settings:")
            st.code(prompt_for(src, pmode, last_month), language=None, wrap_lines=True, height=320)
            answer = st.text_area(f"{p['service']}의 답", key=f"report_{src}", height=160, placeholder="## 기간과 사용량\n…")
            blocked = False
            if answer.strip():
                empty = emptiness(answer)
                if empty >= 0.7:  # 그 AI가 내 기록을 못 본 답 → 분석을 흐리므로 기본은 저장 안 함
                    st.warning(f"이 답은 섹션 {empty:.0%}가 '기록 없음'이에요. {p['service']}가 이전 대화를 볼 수 없는 상태라 "
                               "저장해도 분석에 도움이 안 됩니다. 아래 **B. 전체 대화 기록**(내보내기 파일)로 넣어 주세요.",
                               icon=":material/block:")
                    blocked = not st.checkbox("그래도 저장하기", key=f"force_{src}")
                else:
                    n = len(split_report(answer))
                    st.caption(f":material/check_circle: 섹션 {n}개로 나뉘어 저장됩니다 · 비어 있는 섹션 {empty:.0%}")
            if st.button("보고서 저장", key=f"save_{src}", type="primary", icon=":material/save:",
                         disabled=not answer.strip() or blocked):
                res = store.replace_conversation(importers.self_report(src, answer, names, mode=pmode)[0])  # 같은 날 다시 저장하면 덮어씀
                search.build()
                st.toast(f"{p['service']} 보고서를 {res['messages']}개 섹션으로 저장했습니다", icon=":material/check:")
            st.divider()
            need = src in ("chatgpt", "gemini")
            st.markdown(f"**B. 전체 대화 기록 (내보내기 파일)**" + (" — :red[필수]" if need else " — 선택"))
            st.caption(("오래된 대화는 AI가 기억으로 다 떠올리지 못합니다. 내보내기 파일에는 처음부터 지금까지 전부 들어 있어요. "
                        if need else "") + f"받는 법: {p['export']}")
            folder = st.text_input("압축을 푼 폴더 경로로 넣기", key=f"folder_{src}",
                                   placeholder="예: C:/Users/나/Downloads/takeout-…/Takeout")
            if folder.strip() and st.button("폴더에서 넣기", key=f"folder_btn_{src}", icon=":material/folder_open:"):
                try:
                    with st.spinner("폴더를 읽는 중…"):
                        for desc, convs in importers.from_folder(folder.strip().strip('"'), names):
                            res = store.save_conversations(convs)
                            st.success(f"{desc}: 대화 {res['conversations']:,}개 · 메시지 {res['messages']:,}개를 넣었습니다",
                                       icon=":material/check:")
                        search.build()
                except Exception as exc:
                    st.error(str(exc), icon=":material/error:")
            f = st.file_uploader(f"또는 {p['service']} 내보내기 파일 올리기 (zip / json / html)", type=["zip", "json", "html"],
                                 key=f"file_{src}")
            if f and st.button("대화 기록 넣기", key=f"import_{src}", icon=":material/upload:"):
                try:
                    with st.spinner("읽는 중… (몇 년치면 1분 정도)"):
                        kind, convs = importers.detect_and_parse(f.name, f.getvalue(), names)
                        res = store.save_conversations(convs)
                        search.build()
                    st.success(f"{kind}: 대화 {res['conversations']:,}개 · 메시지 {res['messages']:,}개를 넣었습니다", icon=":material/check:")
                except importers.ManifestError as exc:  # claude.ai 는 링크 목록이 먼저 온다
                    st.warning(str(exc) + " — 링크는 claude.ai에 로그인한 브라우저에서만 열리고, 24시간 안에 한 번만 받을 수 있어요.",
                               icon=":material/link:")
                    for item in exc.files:
                        st.link_button(f"{item['filename']} · {importers.ManifestError.NEEDED[item['category']]}",
                                       item["export_url"], icon=":material/download:")
                    st.caption("받은 zip들을 한 폴더에 두고 위 '폴더 경로로 넣기'에 그 폴더를 넣거나, zip을 하나씩 여기에 올리세요.")
                except Exception as exc:  # 형식이 다른 파일
                    st.error(f"{f.name}: {exc}", icon=":material/error:")
    st.button("다음: 자동 가져오기", icon=":material/arrow_forward:", on_click=go_step, args=(STEPS[2],))

# ================= 2. 자동 가져오기 =================
elif step == STEPS[2]:
    st.subheader("이 PC에서 자동으로 가져오기")
    st.caption("Claude Code 대화와 GitHub 커밋은 버튼 한 번으로 모입니다. 매달 리포트 전에 한 번씩 눌러 주세요.")
    c1, c2 = st.columns(2)
    with c1.container(border=True, height="stretch"):
        st.markdown(":material/terminal: **Claude Code 대화**")
        st.caption("~/.claude/projects 의 기록")
        if st.button("가져오기", key="cc", icon=":material/sync:"):
            with st.spinner("읽는 중…"):
                res = store.save_conversations(importers.claude_code(DEFAULT_ROOT, names))
                search.build()
            st.success(f"새 메시지 {res['messages']}개", icon=":material/check:")
    with c2.container(border=True, height="stretch"):
        st.markdown(":material/commit: **GitHub 커밋**")
        st.caption("내 저장소의 내 커밋 (포크 제외, gh 로그인 필요)")
        if st.button("가져오기", key="gh", icon=":material/sync:"):
            with st.spinner("저장소를 도는 중… (1분 안팎)"):
                try:
                    res = store.save_conversations(importers.github(names))
                    search.build()
                    st.success(f"새 커밋 {res['messages']}개", icon=":material/check:")
                except Exception as exc:
                    st.error(f"GitHub를 읽지 못했습니다: {exc}", icon=":material/error:")
    st.button("다음: 리포트 만들기", icon=":material/arrow_forward:", on_click=go_step, args=(STEPS[3],))

# ================= 3. 리포트 만들기 =================
else:
    st.subheader("AI 컨설턴트에게 종합 리포트 맡기기")
    st.caption("섹션마다 '검색 → 컨설턴트 작성 → 근거 검증 → 실패하면 다시 쓰기'. Gemini에는 검색으로 고른 일부 기록(가린 것)·통계·각 AI의 보고서만 보냅니다.")
    if not over:
        st.info("먼저 1·2단계에서 기록을 모아 주세요.", icon=":material/arrow_back:")
        st.stop()
    if not has_initial:
        st.info("처음이라면 **전체 (초기 총정리)** 를 먼저 만드세요. 지금까지의 모든 기록이 기준선이 되고, 이후 월간 리포트가 이것과 비교됩니다.",
                icon=":material/flag:")
    with st.container(border=True):
        options = ["전체 (초기 총정리)", "지난달", "달 고르기", "직접"]
        mode = st.segmented_control("기간", options, default=options[0] if not has_initial else "지난달")
        today = date.today()
        firsts = [r["first"][:10] for r in over.values() if r.get("first")]
        if mode == "지난달":
            y, m = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
            since, until = date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
            label, kind = f"{y}-{m:02d}", "월간"
        elif mode == "달 고르기":
            months = sorted({f[:7] for f in firsts} | {r["last"][:7] for r in over.values() if r.get("last")})
            ym = st.selectbox("달", months, index=len(months) - 1)
            y, m = map(int, ym.split("-"))
            since, until = date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
            label, kind = ym, "월간"
        elif mode == "직접":
            c1, c2 = st.columns(2)
            since = c1.date_input("시작", value=today.replace(day=1))
            until = c2.date_input("끝", value=today)
            label, kind = f"{since}_{until}", "기간"
        else:
            since, until = date.fromisoformat(min(firsts)), today
            label, kind = "0-initial-agent", "초기 총정리"

        def src_label(s: str) -> str:
            r = over.get(s, {})
            n = (r.get("user_msgs") or 0) + (r.get("commits") or 0)
            rep = " · 보고서" if r.get("report_parts") else ""
            return f"{store.SOURCES[s][0]} ({n:,}{rep})" if r else f"{store.SOURCES[s][0]} (없음)"

        srcs = st.pills("포함할 서비스", list(store.SOURCES), selection_mode="multi",
                        default=[s for s in store.SOURCES if s in over], format_func=src_label)
        missing = [store.SOURCES[s][0] for s in (srcs or []) if s not in over]
        if missing:
            st.caption(f":orange[{', '.join(missing)}] 은(는) 아직 기록이 없어 빠집니다. 1단계에서 보고서를 넣어 주세요.")
        with_tools = st.toggle("연계 추천 포함 (Google 검색으로 새 기술·플러그인·스킬 찾기)", value=True)
        with st.container(horizontal=True, vertical_alignment="bottom"):
            key = key_input()
            model = st.selectbox("모델", [DEFAULT_MODEL, "gemini-flash-lite-latest", "gemini-pro-latest"])
        st.caption(f"저장 이름: reports/{label}.analysis.json · 기간 {since} ~ {until}")
        use = [s for s in (srcs or []) if s in over]
        go = st.button("리포트 만들기", type="primary", icon=":material/auto_awesome:", disabled=not (key and use))

    if go:
        previous = next((r for r in reversed(reports) if r["period"]["until"] < since.isoformat()), None)
        prev_me = None
        if previous:
            me = load_me(previous["label"])
            disliked = []
            for k, v in me.get("reactions", {}).items():
                if v == 0 and "." in k:
                    sec, idx = k.split(".", 1)
                    items = previous.get(sec)
                    if isinstance(items, list) and idx.isdigit() and int(idx) < len(items):
                        disliked.append(items[int(idx)].get("title") or items[int(idx)].get("name", ""))
            prev_me = {"disliked": disliked, "goals": me.get("goals", [])}
        with st.status("AI 컨설턴트가 분석 중…", expanded=True) as status:
            try:
                data = agent.generate_report(
                    get_llm(key, model), since.isoformat(), until.isoformat(), label, kind, sources=use,
                    previous=previous, prev_me=prev_me, progress=lambda msg: st.write(msg), model_name=model,
                    searcher=gemini_web_search(key, model) if with_tools else None,
                    inventory=inventory.collect() if with_tools else None)
                errs = agent.save_report(data)
                load_reports.clear()
                status.update(label="완료", state="complete")
                if errs:
                    st.warning("형식 경고: " + " / ".join(errs[:5]), icon=":material/warning:")
                st.session_state.report_label = label
            except Exception as exc:
                status.update(label="실패", state="error")
                st.error(f"리포트를 만들지 못했습니다: {exc}", icon=":material/error:")
                st.stop()
        if st.button("리포트 보러 가기", type="primary", icon=":material/article:"):
            st.switch_page("app_pages/report.py")
