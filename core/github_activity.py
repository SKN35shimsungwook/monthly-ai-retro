"""GitHub 활동 집계. 로그인된 gh CLI를 그대로 쓴다(토큰을 따로 저장하지 않음)."""
import json
import re
import subprocess
from collections import Counter
from datetime import date

_CONVENTIONAL = re.compile(r"^(feat|fix|docs|refactor|test|style|chore|perf|build|ci)(\(.+\))?: .*[가-힣]")


def _gh(args: list[str]) -> str:
    result = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8", timeout=120)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gh 명령 실패")
    return result.stdout


def _gh_lines(args: list[str]) -> list[dict]:
    """--jq 로 한 줄에 객체 하나씩 받는다(--paginate 페이지 합치기 문제를 피함)."""
    return [json.loads(line) for line in _gh(args).splitlines() if line.strip()]


def collect(since: date, until: date) -> dict:
    """since~until 기간에 내가 만든 저장소와 내 커밋을 센다. gh가 없으면 error만 돌려준다."""
    try:
        login = _gh(["api", "user", "--jq", ".login"]).strip()
        repos = json.loads(_gh(["repo", "list", login, "--limit", "300", "--json",
                                "name,createdAt,pushedAt,isPrivate,isFork,url,homepageUrl,description"]))
    except (RuntimeError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {"error": f"GitHub 정보를 가져오지 못했습니다: {exc}"}

    s, u = since.isoformat(), until.isoformat()
    created = [r for r in repos if s <= r["createdAt"][:10] <= u and not r.get("isFork")]
    active = [r for r in repos if r.get("pushedAt", "")[:10] >= s]

    commits_by_repo = Counter()
    commits_by_day = Counter()
    conventional = 0
    total = 0
    for repo in active:
        try:
            items = _gh_lines(["api", "--paginate",
                               f"repos/{login}/{repo['name']}/commits?author={login}"
                               f"&since={s}T00:00:00%2B09:00&until={u}T23:59:59%2B09:00&per_page=100",
                               "--jq", ".[] | {m: .commit.message, d: .commit.author.date}"])
        except RuntimeError:
            continue  # 빈 저장소 등
        for c in items:
            msg = (c.get("m") or "").splitlines()[0] if c.get("m") else ""
            day = (c.get("d") or "")[:10]
            commits_by_repo[repo["name"]] += 1
            if day:
                commits_by_day[day] += 1
            total += 1
            if _CONVENTIONAL.match(msg):
                conventional += 1

    def slim(r: dict) -> dict:
        return {
            "name": r["name"],
            "private": r["isPrivate"],
            "created": r["createdAt"][:10],
            "url": r["url"],
            "deploy": r.get("homepageUrl") or "",
            "description": r.get("description") or "",
        }

    return {
        "login": login,
        "repos_total": len(repos),
        "repos_created": [slim(r) for r in sorted(created, key=lambda r: r["createdAt"])],
        "commits": total,
        "commit_days": len(commits_by_day),
        "commits_by_repo": commits_by_repo.most_common(15),
        "commits_by_day": dict(sorted(commits_by_day.items())),
        "conventional_rate": round(conventional * 100 / total, 1) if total else None,
    }
