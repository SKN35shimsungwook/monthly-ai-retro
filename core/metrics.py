"""AI 활용 지표 정의와 메시지 분류.

양(커밋 수, 세션 수)이 아니라 질을 보는 지표만 둔다.
판정은 키워드 규칙이라 놓치는 경우가 있다. 앱에서 고친 예외는
rules_override.json 으로 저장해 다음 달부터 반영한다.
"""
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Metric:
    key: str
    group: str
    label: str
    desc: str
    kind: str  # "rate"(작업 요청 중 비율, %) | "count"(횟수) | "value"(그 밖의 값)
    better: str  # "up" | "down"
    pattern: str = ""


GROUPS = ["요청 품질", "재작업·막힘", "세션 관리", "이해·학습"]

METRICS: list[Metric] = [
    # 요청 품질
    Metric("criteria_rate", "요청 품질", "끝난 기준을 붙인 요청",
           "통과 조건·기대 결과·기준을 함께 준 작업 요청 비율", "rate", "up",
           r"기준|조건|통과 조건|통과하면|통과할 때까지|기대 결과|예상 결과|확인되면|되어야|돼야|이어야|예시 입력|합격"),
    Metric("plan_first_rate", "요청 품질", "계획을 먼저 세운 요청",
           "구현 전에 계획·설계·질문을 요청한 비율", "rate", "up",
           r"계획|설계|로드맵|세부사항|질문해|질문하면서|물어봐|기획"),
    Metric("evidence_rate", "요청 품질", "증거를 요구한 요청",
           "완료 보고에 캡처·로그·테스트 결과를 요구한 비율", "rate", "up",
           r"캡처|캡쳐|스크린샷|로그|테스트 결과|결과 보여|증거|출력 보여"),
    Metric("overloaded_rate", "요청 품질", "요구가 4개 이상 섞인 요청",
           "한 메시지에 요구 동사가 4개 이상 들어간 비율", "rate", "down"),
    # 재작업·막힘
    Metric("redo_count", "재작업·막힘", "다시 고치라는 요청",
           "안 된다·아직도·다시 등 재작업 요청 횟수", "count", "down",
           r"안돼|안 돼|안되|안됨|아직도|여전히|다시 해|다시 확인|다시 점검|또 오류|오류 뜬|오류떠|오류 나"),
    Metric("distrust_count", "재작업·막힘", "불신·답답함 표현",
           "'다 확인했다며', '제대로 해' 같은 표현 횟수", "count", "down",
           r"했다며|다며|다메|제대로 해|제대로 하|못믿|못 믿|신뢰가 없|하나도 안|하라고|시발|미쳤|씹었"),
    Metric("interrupt_count", "재작업·막힘", "작업을 중간에 끊은 횟수",
           "Claude 작업을 Esc 등으로 멈춘 횟수", "count", "down"),
    Metric("limit_count", "재작업·막힘", "사용량 한도 도달",
           "작업 중 사용량 한도에 걸린 횟수", "count", "down"),
    # 세션 관리
    Metric("session_median_msgs", "세션 관리", "세션당 메시지(중간값)",
           "한 대화창에 보낸 메시지 수의 중간값", "value", "down"),
    Metric("long_session_count", "세션 관리", "긴 세션(메시지 50개 이상)",
           "주제를 바꾸지 않고 너무 오래 쓴 세션 수", "count", "down"),
    Metric("multi_day_session_count", "세션 관리", "3일 넘게 이어진 세션",
           "시작과 끝이 3일 이상 떨어진 세션 수", "count", "down"),
    Metric("short_go_rate", "세션 관리", "15자 이하 짧은 지시",
           "'진행해', 'ㄱㄱ' 같은 짧은 지시 비율", "rate", "down"),
    # 이해·학습
    Metric("why_rate", "이해·학습", "설명·이유를 물은 메시지",
           "왜·이유·설명·개념을 물은 비율", "rate", "up",
           r"왜 |왜\?|이유|설명|개념|원리|이해가|이해 안|어떻게 작동|무슨 뜻|뭐야|뭐지|차이"),
    Metric("verify_rate", "이해·학습", "점검·검증을 요청한 메시지",
           "점검·검증·테스트를 요청한 비율", "rate", "up",
           r"점검|검증|테스트|시뮬|확인해"),
    Metric("paste_error_count", "이해·학습", "에러를 그대로 붙여넣은 횟수",
           "Traceback·Error 원문만 붙여넣은 메시지 수", "count", "down"),
]

METRIC_BY_KEY = {m.key: m for m in METRICS}

_REQUEST_VERBS = re.compile(r"해줘|해 줘|하고|추가|바꿔|변경|수정|만들어|넣어|빼고|없애|보여|정리|올려")
_ERROR_PASTE = re.compile(r"Traceback|Error:|ERROR|Exception|에러|오류", re.I)
_PASTED = re.compile(r"<pasted_content|^```|^PS [A-Z]:\\|^\(.*\) PS ", re.M)


def is_work_request(text: str) -> bool:
    """비율 지표의 분모: 10자 이상이고 로그만 붙여넣은 게 아닌 메시지."""
    t = text.strip()
    if len(t) < 10:
        return False
    if _PASTED.search(t[:200]) and not _REQUEST_VERBS.search(t[-200:]):
        return False
    return True


def classify(text: str, overrides: dict | None = None) -> set[str]:
    """한 메시지가 해당하는 지표 키 목록. overrides는 {"metric_key": ["제외할 문장 일부", ...]}."""
    hits = set()
    t = text.strip()
    head = t[:1500]
    for m in METRICS:
        if m.pattern and re.search(m.pattern, head):
            hits.add(m.key)
    if len(_REQUEST_VERBS.findall(head)) >= 4:
        hits.add("overloaded_rate")
    if len(t) <= 15:
        hits.add("short_go_rate")
    if _ERROR_PASTE.search(head[:300]) and len(_REQUEST_VERBS.findall(t[-300:])) == 0 and len(t) > 80:
        hits.add("paste_error_count")
    for key, needles in (overrides or {}).items():
        if key in hits and any(n and n in t for n in needles):
            hits.discard(key)
    return hits


def fmt(key: str, value) -> str:
    """지표 값을 단위와 함께 표시: 비율 %, 세션 수·메시지 수 개, 나머지 회."""
    if value is None:
        return "-"
    m = METRIC_BY_KEY[key]
    if m.kind == "rate":
        return f"{value}%"
    return f"{value}개" if key == "session_median_msgs" or key.endswith("session_count") else f"{value}회"


def compare(key: str, now: float | None, before: float | None) -> str:
    """지난 기간 대비 좋아졌는지: 'better' | 'worse' | 'same' | 'na'."""
    if now is None or before is None:
        return "na"
    m = METRIC_BY_KEY[key]
    if abs(now - before) < 1e-9:
        return "same"
    up = now > before
    return "better" if up == (m.better == "up") else "worse"
