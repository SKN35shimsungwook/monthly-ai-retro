import streamlit as st

from core import agent, store
from core.llm import DEFAULT_MODEL, get_llm
from core.ui import key_input

st.title("AI 컨설턴트에게 묻기")
st.caption("내 AI 사용기록에서 관련 대화를 찾아(RAG) 컨설턴트가 근거와 함께 답합니다. 대화는 저장되지 않습니다.")

over = store.overview()
if not over:
    st.info("먼저 '만들기' 화면에서 사용기록을 모아 주세요.", icon=":material/arrow_back:")
    st.stop()

srcs = st.pills("검색할 서비스", [r["source"] for r in over], selection_mode="multi",
                default=[r["source"] for r in over], format_func=lambda s: store.SOURCES[s][0])
key = key_input()

if not st.session_state.get("chat"):
    examples = ["내가 가장 자주 막히는 상황은?", "ChatGPT·Gemini에서 조사한 걸 Claude로 어떻게 넘겼어?",
                "기술영업 면접에서 말할 만한 AI 활용 사례는?", "10월이 8월보다 나아진 점은?"]
    pick = st.pills("이렇게 물어볼 수 있어요", examples, key="ask_example")
    if pick:
        st.session_state.pending_q = pick

st.session_state.setdefault("chat", [])
for turn in st.session_state.chat:
    with st.chat_message(turn["role"]):
        st.markdown(turn["text"])
        if turn.get("hits"):
            with st.expander(f"찾은 기록 {len(turn['hits'])}개", icon=":material/search:"):
                for h in turn["hits"]:
                    st.caption(f"**{h['doc']}** · {store.SOURCES[h['source']][0]} · {h['ts'][:16].replace('T', ' ')} · {h['title']}")
                    st.markdown(f"> {' '.join(h['text'].split())[:300]}")

question = st.chat_input("내 AI 사용에 대해 물어보세요", disabled=not key) or st.session_state.pop("pending_q", None)
if question and key:
    st.session_state.chat.append({"role": "user", "text": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("기록 검색 → 답변 → 근거 검증 중…"):
            try:
                out = agent.build_ask_graph(get_llm(key, DEFAULT_MODEL)).invoke({"question": question, "sources": srcs})
                ans = out["answer"]
                text = ans.get("answer", "")
                if ans.get("advice"):
                    text += f"\n\n:material/lightbulb: **해 볼 것** · {ans['advice']}"
                if out.get("errors"):
                    text += f"\n\n:orange[근거 검증 경고: {out['errors'][0]}]"
            except Exception as exc:
                out, text = {"hits": []}, f":red[답하지 못했습니다: {exc}]"
        st.markdown(text)
    st.session_state.chat.append({"role": "assistant", "text": text, "hits": out.get("hits", [])})
    st.rerun()
