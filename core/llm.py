"""LLM 연결. 기본은 Gemini, 초기 총정리처럼 큰 작업은 ChatGPT API도 쓸 수 있다. 테스트에서는 FakeLLM."""
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


OPENAI_MODELS = ["gpt-4.1-mini", "gpt-4o-mini", "gpt-5-mini"]
GEMINI_MODELS = [DEFAULT_MODEL, "gemini-flash-lite-latest", "gemini-pro-latest"]
GAP = {"gemini": 6.0, "openai": 0.5}  # 호출 사이 최소 간격(초). Gemini 무료는 분당 요청 수가 적다


def provider_of(model: str) -> str:
    return "openai" if model.startswith(("gpt", "o1", "o3", "o4")) else "gemini"


class QuotaError(RuntimeError):
    """기다려도 풀리지 않는 한도(하루 한도·크레딧 없음). 바로 멈추고 이유를 알린다."""


def _is_rate_limit(msg: str) -> bool:
    return any(w in msg for w in ("429", "RESOURCE_EXHAUSTED", "rate limit", "Rate limit", "rate_limit"))


def _wait_seconds(msg: str, tries: int) -> float:
    """오류 안에 '몇 초 뒤 다시'가 있으면 그만큼, 없으면 15·30·60초…"""
    m = (re.search(r"retry in (\d+(?:\.\d+)?)\s*s", msg, re.I)
         or re.search(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s", msg)
         or re.search(r"try again in (\d+(?:\.\d+)?)\s*s", msg, re.I))
    return min(float(m.group(1)) + 2, 90) if m else min(15 * 2 ** tries, 90)


_last_call = {"gemini": 0.0, "openai": 0.0}


def call_with_retry(fn, provider: str = "gemini", notify=None, max_waits: int = 6):
    """호출 사이 간격을 두고, 429(분당 한도)가 나면 안내된 시간만큼 기다렸다 다시 한다.
    하루 한도·크레딧 부족처럼 기다려도 안 풀리는 경우는 QuotaError 로 바로 멈춘다."""
    import time

    notify = notify or (lambda _m: None)
    for tries in range(max_waits + 1):
        gap = GAP.get(provider, 0) - (time.monotonic() - _last_call.get(provider, 0))
        if gap > 0:
            time.sleep(gap)
        try:
            return fn()
        except Exception as exc:  # SDK마다 예외 종류가 달라 글자로 판단
            msg = str(exc)
            if "insufficient_quota" in msg:
                raise QuotaError("ChatGPT API 크레딧이 없어요. platform.openai.com 의 Billing 에서 충전한 뒤 다시 눌러 주세요. "
                                 "끝난 부분은 저장돼 있어 이어서 만듭니다.") from exc
            if not _is_rate_limit(msg):
                raise
            if "PerDay" in msg or "per day" in msg.lower():
                raise QuotaError("Gemini 하루 한도를 다 썼어요. 내일 다시 누르거나 ChatGPT 모델로 바꿔 주세요. "
                                 "끝난 부분은 저장돼 있어 이어서 만듭니다.") from exc
            if tries == max_waits:
                raise QuotaError(f"한도에 {max_waits}번 연속 걸렸어요. 몇 분 뒤 다시 눌러 주세요. "
                                 "끝난 부분은 저장돼 있어 이어서 만듭니다.") from exc
            wait = _wait_seconds(msg, tries)
            notify(f":orange[분당 한도에 걸려 {wait:.0f}초 기다렸다가 다시 시도합니다 ({tries + 1}/{max_waits})]")
            time.sleep(wait)
        finally:
            _last_call[provider] = time.monotonic()


class PacedLLM:
    """LangChain 모델을 감싸 invoke 마다 간격·자동 재시도를 붙인다. notify 는 나중에 바꿔 끼울 수 있다."""

    def __init__(self, llm, provider: str, notify=None):
        self.llm, self.provider, self.notify = llm, provider, notify

    def invoke(self, messages):
        return call_with_retry(lambda: self.llm.invoke(messages), self.provider, self.notify)


def get_llm(api_key: str, model: str = DEFAULT_MODEL, temperature: float = 0.3, notify=None):
    provider = provider_of(model)
    if provider == "openai":
        from langchain_openai import ChatOpenAI

        extra = {} if model.startswith(("gpt-5", "o")) else {"temperature": temperature}  # gpt-5 계열은 온도 고정
        llm = ChatOpenAI(model=model, api_key=api_key, max_retries=0, timeout=180, **extra)
    else:
        from langchain_google_genai import ChatGoogleGenerativeAI

        llm = ChatGoogleGenerativeAI(model=model, google_api_key=api_key, temperature=temperature, max_retries=0)
    return PacedLLM(llm, provider, notify)


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
