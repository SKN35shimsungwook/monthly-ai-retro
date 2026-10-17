"""민감정보 가리기.

수집기가 대화 내용 일부(예시 문장)를 요약 파일에 넣기 전에,
그리고 블로그에 올리기 직전에 한 번 더 이 함수를 거친다.
"""
import re

# (패턴, 바꿀 글자) 순서가 중요하다. 구체적인 키 패턴을 먼저 잡고, 마지막에 긴 토큰을 잡는다.
_PATTERNS = [
    (re.compile(r"sk-(?:proj-|ant-)?[A-Za-z0-9_\-]{16,}"), "[API_KEY]"),
    (re.compile(r"AIza[0-9A-Za-z_\-]{30,}"), "[API_KEY]"),
    (re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"), "[GITHUB_TOKEN]"),
    (re.compile(r"hf_[A-Za-z0-9]{20,}"), "[API_KEY]"),
    (re.compile(r"xox[abprs]-[A-Za-z0-9\-]{10,}"), "[API_KEY]"),
    # DB_PASSWORD=..., OPENAI_API_KEY = "..." 같은 .env 줄도 잡는다
    (re.compile(r"(?i)(\w*(?:password|passwd|pwd|secret|token|api[_-]?key|authtoken)\w*)\s*[:=]\s*[\"']?[^\s\"']+[\"']?"),
     r"\1=[HIDDEN]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[EMAIL]"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"), "[IP]"),
    (re.compile(r"(?i)[A-Z]:[\\/]+Users[\\/]+[^\\/\s\"']+"), "~"),
    (re.compile(r"/c/Users/[^/\s\"']+", re.I), "~"),
    # 긴 무작위 문자열. 도메인 일부(xxx.streamlit.app)나 URL 경로 조각은 제외
    (re.compile(r"(?<![\w./-])[A-Za-z0-9_\-]{36,}(?![\w.-])"), "[TOKEN]"),
]


def redact(text: str, names: list[str] | None = None) -> str:
    """키·토큰·이메일·IP·사용자 경로·지정한 이름을 가린다."""
    if not text:
        return ""
    out = text
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    for name in names or []:
        name = name.strip()
        if name:
            out = out.replace(name, "[이름]")
    return out


def find_leaks(text: str, names: list[str] | None = None) -> list[str]:
    """게시 전 검사용. 가려야 할 것이 남아 있으면 그 종류를 돌려준다."""
    found = []
    for pattern, repl in _PATTERNS:
        # 이미 가린 자리(password=[HIDDEN] 등)는 새는 것이 아니다
        if any("[HIDDEN]" not in m.group(0) for m in pattern.finditer(text)):
            found.append(repl)
    for name in names or []:
        if name.strip() and name.strip() in text:
            found.append("[이름]")
    return sorted(set(found))
