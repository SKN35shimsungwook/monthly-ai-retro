import streamlit as st

st.title("도움말")
st.markdown("LangChain 챗봇처럼 **DB → 검색(RAG) → LLM 컨설턴트 → 근거 검증** 구조의 종합 AI 활용 분석 에이전트입니다.")

st.graphviz_chart("""
digraph {
  rankdir=LR; node [shape=box, style="rounded,filled", fillcolor="#F3F0FF", color="#6C5CE7", fontname="sans-serif"];
  p [label="사용 실태\n(용도·빈도·시작 시기)"];
  a [label="각 AI의 사용 보고서\n(맞춤 프롬프트)"]; a2 [label="전체 대화 기록\n(내보내기 파일·Claude Code)"]; a3 [label="GitHub 커밋"];
  b [label="민감정보 가리기"]; c [label="로컬 DB"]; d [label="로컬 검색"];
  e [label="컨설턴트 작성\n(Gemini)"]; f [label="근거 검증"]; w [label="웹 검색\n연계 추천"];
  g [label="리포트 · 타임라인 · 묻기"];
  p -> a; a -> b; a2 -> b; a3 -> b; b -> c -> d -> e -> f -> g; f -> e [label="재시도", fontsize=10];
  f -> w -> g;
}
""")

with st.container(border=True):
    st.markdown("**처음 한 번 — 기준선(0회차) 만들기**")
    st.markdown(
        "1. **1 만들기 → 0 사용 실태**: AI별 용도·자주 쓰는 순서 고르기 → 프롬프트가 여기에 맞춰짐\n"
        "2. **1 만들기 → 1 AI 보고서 받기** (서비스마다)\n"
        "   - A. '초기 설정' 프롬프트를 붙여넣고 받은 답 저장\n"
        "   - B. **ChatGPT·Gemini는 내보내기 파일 필수** — 몇 년 전 대화는 AI가 기억으로 다 못 떠올리기 때문\n"
        "3. **1 만들기 → 2 자동 가져오기**: Claude Code 대화 · GitHub 커밋\n"
        "4. **1 만들기 → 3 리포트 만들기**: 기간 '전체 (초기 총정리)', 서비스 모두 선택 → 처음 쓴 달부터 오늘까지 분석")
with st.container(border=True):
    st.markdown("**매달**")
    st.markdown(
        "1. **2 자동 가져오기** (ChatGPT·Gemini는 분기에 한 번 내보내기 파일을 다시 올리면 충분)\n"
        "2. **3 리포트 만들기**: 기간 '지난달' → 기준선·지난 목표와 자동 비교\n"
        "3. **2 리포트**에서 👍/👎·목표 고르기 → **3 타임라인**에서 변화 보기 → 궁금한 건 **4 묻기**")

st.caption("원본 기록은 이 PC(data/db)에만 있고 커밋되지 않습니다. Gemini에는 검색으로 고른 일부 기록(가린 것)·통계·각 AI의 보고서만 보냅니다.")
