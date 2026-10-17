import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import analysis, claude_logs  # noqa: E402
from core.metrics import METRICS, classify, compare, is_work_request  # noqa: E402
from core.redact import find_leaks, redact  # noqa: E402


# ---- 민감정보 가리기 ----
def test_redact_keys_and_tokens():
    text = ("키는 sk-proj-abcdefghijklmnop1234567890 이고 AIzaSyA1234567890abcdefghijklmnopqrstu 와 "
            "ghp_abcdefghijklmnopqrstuvwxyz123456 도 있다")
    out = redact(text)
    assert "sk-proj" not in out and "AIza" not in out and "ghp_" not in out
    assert out.count("[API_KEY]") == 2 and "[GITHUB_TOKEN]" in out


def test_redact_password_email_ip_path_names():
    out = redact("DB_PASSWORD=hunter2 메일 someone@example.com 서버 10.20.30.40 "
                 r"경로 C:\Users\testuser\Desktop 팀원 홍길동", names=["홍길동"])
    for leaked in ("hunter2", "@example.com", "10.20.30", "testuser", "홍길동"):
        assert leaked not in out
    assert find_leaks(out, ["홍길동"]) == []


def test_streamlit_url_is_not_a_token():
    url = "https://machine-learning-deep-learning-quiz-bohfsvfryhncd2asfzjcrg.streamlit.app/"
    assert redact(url) == url and find_leaks(url) == []
    assert redact("토큰 abcdefghijklmnopqrstuvwxyz0123456789ABCD 끝") == "토큰 [TOKEN] 끝"


def test_find_leaks_detects_unredacted():
    assert "[API_KEY]" in find_leaks("sk-abcdefghijklmnopqrstuvwx")
    assert find_leaks("평범한 문장입니다") == []


# ---- 지표 분류 ----
def test_classify_examples():
    assert "criteria_rate" in classify("끝난 기준: 선택지 4개가 모두 달라야 하고 원본과 같아야 한다. 이걸로 점검해줘")
    assert "redo_count" in classify("이거 아직도 안되는데 다시 확인해봐")
    assert "distrust_count" in classify("오류 다 확인했다며 이거 3번 4번 답 같음")
    assert "why_rate" in classify("이 코드가 왜 이렇게 동작하는지 개념이랑 같이 설명해줘")
    assert "short_go_rate" in classify("진행해")
    assert "overloaded_rate" in classify("버튼 추가하고 색 바꿔줘 그리고 표 수정해주고 링크 넣어줘 마지막으로 정리해줘")


def test_override_removes_false_positive():
    msg = "과락 기준표를 화면에 보여줘"
    assert "criteria_rate" in classify(msg)
    assert "criteria_rate" not in classify(msg, {"criteria_rate": ["과락 기준표"]})


def test_work_request_excludes_short_and_pasted_logs():
    assert not is_work_request("ㄱㄱ")
    assert not is_work_request("<pasted_content id='1'>\nTraceback (most recent call last):\n  File x\n</pasted_content>")
    assert is_work_request("이 화면에 오답노트 버튼을 추가해줘")


def test_compare_direction():
    assert compare("criteria_rate", 20, 10) == "better"
    assert compare("redo_count", 20, 10) == "worse"
    assert compare("redo_count", None, 10) == "na"


# ---- 기록 집계 (가짜 jsonl) ----
def _write_session(dirpath: Path, sid: str, rows: list[tuple[str, str]]):
    lines = [json.dumps({"type": "ai-title", "sessionId": sid, "aiTitle": "테스트 세션"})]
    for i, (ts, text) in enumerate(rows):
        lines.append(json.dumps({"type": "user", "sessionId": sid, "uuid": f"{sid}-{i}", "timestamp": ts,
                                 "cwd": "C:/proj/demo", "message": {"role": "user", "content": text}}))
        lines.append(json.dumps({"type": "assistant", "sessionId": sid, "uuid": f"{sid}-a{i}", "timestamp": ts,
                                 "message": {"model": "claude-test", "content": [
                                     {"type": "tool_use", "name": "Bash", "input": {}}]}}))
    (dirpath / f"{sid}.jsonl").write_text("\n".join(lines), encoding="utf-8")


def test_collect_filters_period_dedupes_and_redacts(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    rows = [("2026-10-01T01:00:00Z", "끝난 기준을 정해서 점검해줘 키 sk-abcdefghijklmnopqrstuvwx"),
            ("2026-10-01T02:00:00Z", "진행해"),
            ("2026-11-05T01:00:00Z", "11월 메시지는 빠져야 한다")]
    _write_session(proj, "s1", rows)
    _write_session(proj, "s1copy", rows[:1])  # 이어하기로 복사된 세션(같은 메시지)
    out = claude_logs.collect(date(2026, 10, 1), date(2026, 10, 31), tmp_path)
    assert out["user_messages"] == 2
    assert out["metrics"]["criteria_rate"]["numerator"] == 1
    assert out["metrics"]["short_go_rate"]["value"] is not None
    assert all("sk-" not in e for exs in out["examples"].values() for e in exs)
    assert out["session_list"][0]["title"] == "테스트 세션"
    assert out["tool_calls"] == 3


# ---- 분석 리포트 ----
SAMPLE = json.loads((ROOT / "data" / "sample" / "sample.analysis.json").read_text(encoding="utf-8"))
INITIAL = ROOT / "reports" / "0-initial.analysis.json"


def test_sample_and_initial_reports_are_valid():
    assert analysis.validate(SAMPLE) == []
    if INITIAL.exists():
        data = json.loads(INITIAL.read_text(encoding="utf-8"))
        assert analysis.validate(data) == []
        assert find_leaks(INITIAL.read_text(encoding="utf-8")) == []


def test_validate_reports_missing_parts():
    bad = {**SAMPLE, "strengths": [{"title": "x"}], "goal_candidates": [{"metric": "없는지표", "target": 1}]}
    del bad["headline"]
    errs = analysis.validate(bad)
    assert any("headline" in e for e in errs)
    assert any("strengths[0].evidence" in e for e in errs)
    assert any("없는지표" in e for e in errs)


def test_goal_check_direction():
    prev_me = {"goals": [{"metric": "criteria_rate", "target": 15, "text": "a"},
                         {"metric": "redo_count", "target": 5, "text": "b"}]}
    now = {"metrics": {"criteria_rate": 20, "redo_count": 9}}
    assert [g["achieved"] for g in analysis.check_goals(prev_me, now)] == [True, False]
    assert analysis.check_goals(None, now) == []


def test_me_roundtrip_and_markdown_drops_thumbs_down(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis, "REPORT_DIR", tmp_path)
    me = {"reactions": {"strengths.0": 0, "strengths.1": 1}, "goals": [SAMPLE["goal_candidates"][0]], "note": "한 줄"}
    analysis.save_me("x", me)
    loaded = analysis.load_me("x")
    assert loaded["reactions"] == me["reactions"] and loaded["note"] == "한 줄"
    md = analysis.to_markdown(SAMPLE, loaded)
    assert SAMPLE["strengths"][0]["why"] not in md
    assert SAMPLE["strengths"][1]["why"] in md
    assert SAMPLE["goal_candidates"][0]["text"] in md and "한 줄" in md


def test_attach_metrics():
    summary = {"claude": {"sessions": 1, "user_messages": 2, "active_days": 1,
                          "metrics": {m.key: {"value": 1} for m in METRICS}},
               "github": {"commits": 5, "repos_created": [{}]}, "blog": {"posts": []}}
    out = analysis.attach_metrics({}, summary)
    assert out["totals"]["commits"] == 5 and out["totals"]["new_repos"] == 1
    assert set(out["metrics"]) == {m.key for m in METRICS}
