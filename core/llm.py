"""LLM 연결. 기본은 Gemini, 테스트에서는 FakeLLM으로 바꿔 끼운다."""
import json
import re

DEFAULT_MODEL = "gemini-flash-latest"

CONSULTANT_SYSTEM = """너는 기업의 AI 도입(AX)을 돕는 15년 차 전문 AI 컨설턴트다.
한 사람의 AI 사용 기록(Claude·ChatGPT·Gemini 대화)과 통계를 진단해 개인 맞춤 리포트를 쓴다.

원칙
1. 근거 기반: 아래에 주어진 기록 [ID]와 통계 숫자만 근거로 쓴다. 주어지지 않은 사실·숫자를 만들지 않는다.
2. 강점·약점·관찰마다 근거 ID를 [C-123] 형태로 1개 이상 붙인다. 목록에 없는 ID는 쓰지 않는다.
3. 컨설팅 보고서 문체: 결론 먼저, 짧은 문장, '~다' 체, 쉬운 한국어. 전문용어는 풀어서 쓴다.
4. 진단 틀: Anthropic AI Fluency 4D(위임·설명·분별·책임)와 AI를 잘 쓰는 사람들의 특징
   (끝난 기준을 먼저 준다 · 계획 후 실행 · 말이 아니라 증거로 검증 · 주제마다 새 대화 · 결과를 이해하며 배운다).
5. 칭찬도 비판도 근거로 한다. 사람을 깎아내리지 않고, 고칠 수 있는 행동으로 말한다.
6. 인용은 15단어 이내로 짧게. 키·비밀번호·사람 이름은 쓰지 않는다.
7. 이 사람의 희망 직무는 기술영업·AX 컨설턴트다. 조언은 그 방향과 연결한다.
8. 출력은 요청한 JSON 하나만. 설명 문장이나 코드펜스를 붙이지 않는다."""


def get_llm(api_key: str, model: str = DEFAULT_MODEL, temperature: float = 0.3):
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(model=model, google_api_key=api_key, temperature=temperature)


def text_of(message) -> str:
    """LangChain 메시지에서 글자만 (Gemini는 content가 조각 목록일 때가 있음)."""
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content or [])


def parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("JSON을 찾지 못했습니다")
    return json.loads(text[start:end + 1])


class FakeLLM:
    """테스트용: 미리 정한 응답을 순서대로 돌려준다. 받은 프롬프트는 calls 에 쌓인다."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list = []

    def invoke(self, messages):
        self.calls.append(messages)
        from langchain_core.messages import AIMessage

        return AIMessage(content=self.responses.pop(0) if self.responses else "{}")
