"""각 AI 서비스에 붙여넣어 '내 사용 보고서'를 받는 프롬프트.

답의 '제목'은 세 서비스가 같다(받은 글을 섹션별로 잘라 DB에서 합치기 위해).
하지만 '기록을 찾는 방법'과 '숫자를 믿을 수 있는 정도', '그 서비스만 아는 것'은 서비스마다 다르다.
- ChatGPT : 메모리 + 이전 대화 참조(요약된 기억). 대화를 하나씩 열어 보지 못한다 → 숫자는 대략만.
- Claude  : 과거 대화 검색 도구(키워드 검색·최근 대화)를 직접 여러 번 호출할 수 있다 → 검색을 반복시킨다.
- Gemini  : 이전 채팅 참조·저장된 정보. 계정 설정에 따라 접근 범위가 다르다 → 접근 여부부터 밝히게 한다.
"""

# 세 서비스 공통 제목 (이 순서, '## ' 포함)
SECTIONS = ["기간과 사용량", "주로 한 일", "요청하는 방식", "잘 쓴 점", "아쉬운 점", "자주 막힌 상황",
            "이 서비스만의 활용", "월별 변화", "추천", "이 서비스가 기억하는 나"]

PROMPTS = {
    "chatgpt": {
        "service": "ChatGPT",
        "before": "설정 → 개인 맞춤 설정에서 **메모리**와 **채팅 기록 참조**를 켠 상태로, **새 채팅**에 붙여넣으세요. "
                  "프로젝트 안이 아니라 일반 채팅에서 하세요. 답이 짧으면 '메모리와 이전 대화를 더 떠올려서 각 제목을 더 자세히'라고 한 번 더 요청하세요.",
        "export": "설정 → 데이터 제어 → 데이터 내보내기 → 메일로 온 zip",
        "how_to_find": """1. 먼저 저장된 메모리 전체를 확인한다.
2. '이전 대화 참조'로 {scope_short} 떠올릴 수 있는 대화를 주제별(코딩·공부·글쓰기·자료조사·업무·일상)로 하나씩 떠올린다.
3. 너는 개별 대화를 열어 정확히 세지 못한다. 그러니 대화 수·비중은 '대략'으로만 쓰고, 정확한 숫자를 지어내지 않는다.""",
        "unique": """## 이 서비스만의 활용
(GPTs · 프로젝트 · 메모리 · 캔버스 · 고급 데이터 분석(코드 실행) · 딥 리서치 · 이미지 생성 · 음성 중
 내가 쓴 흔적이 있는 것 / 없는 것. 내가 만든 GPT나 프로젝트가 있으면 이름과 용도)""",
        "remember": """## 이 서비스가 기억하는 나
(저장된 메모리에 실제로 들어 있는 내 정보를 항목별로: 직업·학습 상황·목표·선호하는 답변 방식·진행 중인 프로젝트.
 메모리에 없는 것은 쓰지 않는다)""",
    },
    "claude_web": {
        "service": "Claude AI",
        "before": "claude.ai 설정에서 **메모리**와 **과거 대화 검색·참조**를 켠 상태로, 프로젝트 밖의 **새 대화**에 붙여넣으세요. "
                  "Claude가 검색 도구를 몇 번 쓰는지 화면에 보입니다. 1~2번만 쓰고 끝나면 '검색을 더 해서 각 제목을 채워줘'라고 한 번 더 요청하세요.",
        "export": "설정 → 개인정보 → 데이터 내보내기 → 메일로 온 zip",
        "how_to_find": """1. 과거 대화 검색 도구를 실제로 여러 번 호출한다. 최소 {min_search}번.
   - 최근 대화 목록을 {scope_short} 넘겨 가며 월별로 훑는다.
   - 키워드 검색: {keywords}.
2. 메모리에 저장된 내용도 확인한다.
3. 찾은 대화 수와 검색 횟수를 '기간과 사용량'에 적는다. 찾지 못한 기간은 '확인 못 함'이라고 쓴다.
4. 이 계정의 claude.ai 대화만 대상이다. Claude Code(터미널·데스크톱 코딩) 기록은 너에게 보이지 않으니 추측하지 않는다.""",
        "unique": """## 이 서비스만의 활용
(프로젝트 · 아티팩트 · 메모리 · 과거 대화 검색 · 커넥터(Google Drive·GitHub 등) · 리서치 · 파일 분석 중
 내가 쓴 흔적이 있는 것 / 없는 것. 만든 프로젝트·아티팩트가 있으면 이름과 용도)""",
        "remember": """## 이 서비스가 기억하는 나
(메모리에 실제로 저장된 내 정보와, 여러 대화에서 반복해서 드러난 나에 대한 사실. 근거 대화 날짜를 함께)""",
    },
    "gemini": {
        "service": "Gemini",
        "before": "Gemini 앱 활동이 켜져 있고 설정의 **이전 채팅 참조(개인 맞춤)**가 켜진 상태에서 **새 채팅**에 붙여넣으세요. "
                  "첫 줄에 '이전 채팅에 접근할 수 없음'이 나오면 설정을 확인하거나, Google 테이크아웃 파일을 아래에 올리세요.",
        "export": "Google 테이크아웃 → '내 활동'만 선택 → 활동 기록 옵션에서 'Gemini 앱'만 → 형식 JSON → zip",
        "how_to_find": """1. 먼저 이전 채팅과 '저장된 정보'에 접근할 수 있는지 확인한다.
   접근할 수 없으면 답 맨 첫 줄에 '이전 채팅에 접근할 수 없음'이라고 쓰고, 각 제목에는 '기록 없음'만 쓴다. 지어내지 않는다.
2. 접근할 수 있으면 {scope_short} 이전 채팅을 주제별로 떠올리고, 내가 만든 Gem과 딥 리서치·Canvas 사용 흔적도 확인한다.
3. 2024년 2월 이전에는 이름이 Bard였다. Bard 시절 대화도 같은 기록으로 본다.
4. 대화 수·비중은 '대략'으로만 쓴다.""",
        "unique": """## 이 서비스만의 활용
(Gem · 딥 리서치 · Canvas · NotebookLM · Google 워크스페이스 연동(Gmail·Drive·Docs) · 이미지·영상 생성 · 검색 연동 중
 내가 쓴 흔적이 있는 것 / 없는 것. 만든 Gem이 있으면 이름과 용도.
 특히 다른 AI 대신 Gemini를 고른 작업이 무엇이었는지)""",
        "remember": """## 이 서비스가 기억하는 나
('저장된 정보'와 이전 채팅에서 드러난 내 정보: 직업·학습 상황·목표·선호. 근거가 없는 것은 쓰지 않는다)""",
    },
}

_TEMPLATE = """너는 지금부터 나의 AI 활용 코치다. '내가 {service}를 어떻게 써 왔는지' 사용 보고서를 써 줘.
나는 Claude·ChatGPT·Gemini를 함께 쓰고, 세 AI의 보고서를 합쳐 내 AI 활용 습관을 고치려고 한다.

조사 범위: {scope}
{focus}

기록을 찾는 방법 ({service}에 맞춤)
{how_to_find}

규칙
- 실제로 확인한 기록만 근거로 쓴다. 확인 못 한 것은 '기록 없음', 추측은 앞에 (추측)을 붙인다.
- 예시는 날짜(YYYY-MM-DD 또는 YYYY-MM)와 대화 주제를 15단어 이내로 든다.
- 비밀번호·API 키·전화번호·주소·다른 사람 이름은 쓰지 않는다.
- 칭찬만 하지 말고 냉정하게. 고칠 수 있는 행동으로 쓴다.
- 아래 제목을 그대로, 이 순서로 쓴다. 제목 앞 '## '도 그대로. 다른 머리말·맺음말은 쓰지 않는다.

## 기간과 사용량
(처음 쓴 시기 ~ 최근, 대략적인 대화 수, 자주 쓴 요일·시간대, 기록을 어떻게 찾았는지)
## 주로 한 일
(주제별 대략 비중과 대표 예시 {n_examples}개)
## 요청하는 방식
(요청 길이, 맥락·조건·완료 기준을 주는지, 한 번에 여러 개를 시키는지, 결과를 확인하는지. 예시 포함)
## 잘 쓴 점
(3~5개, 각각 근거 예시)
## 아쉬운 점
(3~5개, 각각 근거 예시와 그로 인해 생긴 손해)
## 자주 막힌 상황
(같은 문제를 반복해서 다시 요청했거나 답답해했던 상황과 원인)
{unique}
## 월별 변화
({monthly_rule})
## 추천
(내 습관에 맞춰 {service}에서 더 써 볼 기능·설정·프롬프트 습관 3개)
{remember}"""


MODES = {
    "initial": {
        "label": "초기 설정 (처음부터 전체)",
        "scope": "내가 {service}를 처음 사용한 날부터 오늘까지 전체 기간. 이 보고서는 앞으로 매달 비교할 '기준선'이 된다. "
                 "오래된 기록일수록 놓치기 쉬우니 가장 오래된 달부터 차례로 확인한다.",
        "scope_short": "가장 오래된 달까지",
        "min_search": 20,
        "n_examples": "5~8",
        "monthly_rule": "처음 쓴 달부터 이번 달까지 빠짐없이 한 줄씩: YYYY-MM: 주로 한 일 / 달라진 점. 기록이 없는 달은 '기록 없음'",
    },
    "monthly": {
        "label": "월간 (지난달만)",
        "scope": "{month} 한 달만. 그 전 기간은 비교할 때만 짧게 언급한다.",
        "scope_short": "{month} 안에서",
        "min_search": 10,
        "n_examples": "3~5",
        "monthly_rule": "{month}의 주차별 변화, 그리고 그 전 달과 비교해 달라진 점 한두 줄",
    },
}


BASE_KEYWORDS = ["코드", "오류", "배포", "프로젝트", "보고서", "발표", "공부", "시험", "퀴즈", "게임", "자료 조사", "프롬프트"]

_UNSET = object()


def prompt_for(source: str, mode: str = "initial", month: str = "", prof=_UNSET) -> str:
    """mode: initial(처음부터 전체 — 기준선) | monthly(한 달).
    prof: 사용 실태 조사 결과(core.profile). 생략하면 저장된 것을 쓰고, None 이면 맞춤 없이 만든다."""
    from core import profile

    if prof is _UNSET:
        prof = profile.load()
    p, m = PROMPTS[source], MODES[mode]
    fill = {"service": p["service"], "month": month or "지난달"}
    scope_short = m["scope_short"].format(**fill)
    keywords = ", ".join(profile.search_keywords(prof, source, BASE_KEYWORDS))
    how = p["how_to_find"].format(min_search=m["min_search"], scope_short=scope_short, keywords=keywords)
    focus = profile.focus_block(prof, source, p["service"])
    return _TEMPLATE.format(service=p["service"], scope=m["scope"].format(**fill), how_to_find=how,
                            focus=("\n" + focus + "\n") if focus else "",
                            unique=p["unique"], remember=p["remember"], n_examples=m["n_examples"],
                            monthly_rule=m["monthly_rule"].format(**fill))


def _heading(line: str) -> str | None:
    """'## 제목' 줄이거나, 화면에서 복사하느라 '##'가 빠진 '제목(설명…)' 줄이면 제목을 돌려준다."""
    s = line.strip().lstrip("#").strip().strip("*").strip()
    if line.lstrip().startswith("#"):
        return s.split("(")[0].strip() or None
    for name in SECTIONS:
        if s == name or s.startswith(name + "(") or s.startswith(name + " ("):
            return name
    return None


def split_report(text: str) -> list[tuple[str, str]]:
    """받은 보고서를 제목 단위로 자른다. 제목이 하나도 없으면 통째로 한 덩어리."""
    parts, title, buf = [], "전체", []
    for line in text.splitlines():
        head = _heading(line)
        if head:
            if "".join(buf).strip():
                parts.append((title, "\n".join(buf).strip()))
            title, buf = head, []
        else:
            buf.append(line)
    if "".join(buf).strip():
        parts.append((title, "\n".join(buf).strip()))
    return parts


_EMPTY = ("기록 없음", "확인 못 함", "접근할 수 없음", "접근 불가")


def emptiness(text: str) -> float:
    """보고서 섹션 중 내용이 '기록 없음'뿐인 비율 (0~1). 높으면 그 AI가 내 기록을 못 본 것."""
    parts = [body for _t, body in split_report(text)]
    if not parts:
        return 1.0
    empty = 0
    for body in parts:
        lines = [ln.strip(" -*·\t") for ln in body.splitlines() if ln.strip(" -*·\t")]
        meaningful = [ln for ln in lines if not any(e in ln for e in _EMPTY) and not ln.startswith("(")]
        if not meaningful:
            empty += 1
    return empty / len(parts)
