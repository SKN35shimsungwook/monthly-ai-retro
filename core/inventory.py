"""지금 쓰고 있는 AI 도구 목록 (추천에서 이미 있는 것을 빼고, 결합 시너지를 찾는 기준).

이름과 사용 횟수만 읽는다. 계정·토큰 같은 값은 읽지 않는다.
"""
import json
from collections import Counter
from pathlib import Path

HOME = Path.home()
CLAUDE_DIR = HOME / ".claude"


def _claude_json() -> dict:
    p = HOME / ".claude.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _usage(d: dict) -> dict:
    return {k: (v.get("usageCount", 0) if isinstance(v, dict) else v) for k, v in (d or {}).items()}


def tool_calls(root: Path = CLAUDE_DIR / "projects", top: int = 15) -> list[tuple[str, int]]:
    """Claude Code가 실제로 많이 쓴 도구(브라우저, 터미널 등)."""
    counts = Counter()
    for path in root.glob("*/*.jsonl"):
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if '"tool_use"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for part in (rec.get("message") or {}).get("content") or []:
                    if isinstance(part, dict) and part.get("type") == "tool_use":
                        counts[part.get("name", "?").split("__")[-1]] += 1
    return counts.most_common(top)


def collect(include_tools: bool = True) -> dict:
    cj = _claude_json()
    skills_dir = CLAUDE_DIR / "skills"
    return {
        "claude_code_skills_installed": sorted(p.name for p in skills_dir.iterdir() if p.is_dir()) if skills_dir.exists() else [],
        "skills_used": _usage(cj.get("skillUsage")),
        "plugins_used": _usage(cj.get("pluginUsage")),
        "mcp_servers": sorted((cj.get("mcpServers") or {}).keys()),
        "claude_code_tools_top": tool_calls() if include_tools else [],
        "known_stack": ["Python", "Streamlit", "GitHub(gh CLI)", "Gemini API", "OpenAI API", "LangChain/LangGraph",
                        "Google ADK", "TiDB", "RunPod", "Tistory 블로그 자동화(Playwright)"],
    }
