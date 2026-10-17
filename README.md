# 월간 AI 활용 회고 (monthly-ai-retro)

매달 내 Claude Code 사용 기록 · GitHub 활동 · 주간회고 블로그를 바탕으로
**Claude Code가 한 달 대화를 직접 읽고 분석 리포트를 쓰고**, 나는 앱에서 읽으며 👍/👎와 목표만 고르는 회고 도구입니다.

리포트 구성: 요약 · 사용 유형과 방식 · 강점 · 약점 · 보완점과 추천 · 지난 기간 대비 변화 · 나라는 사람 · 다음 목표

## 매달 하는 일 (2단계)

1. Claude Code에 **"월간 리포트 만들어줘"** (처음 한 번은 "초기 총정리 리포트 만들어줘")
   - 스킬 `monthly-ai-report`가 수집 → 지난달 내 메시지 전부 읽기 → 분석 작성 → 형식·민감정보 검사 → `reports/`에 저장
2. `회고앱_실행.bat` → 리포트를 읽고 항목마다 👍/👎, 다음 목표 1~2개 선택 (누르는 즉시 저장, 쓸 것 없음)

다음 리포트에서 지난 목표 달성 여부가 자동으로 나오고, 👎 한 관찰은 반복하지 않습니다.

## 화면

| 화면 | 내용 |
| --- | --- |
| 리포트 | 왼쪽 목차로 섹션 이동, 보고서처럼 위에서 아래로 읽기. 추천 문장은 복사 버튼으로 바로 Claude에게 |
| 타임라인 | 지표 추이 그래프, 월별 리포트 카드(내 반응·고른 목표·지난 목표 달성) |
| 만드는 법 | 위 2단계 안내와 직접 실행 명령어 |

## 어떻게 돌아가나

```
[내 PC]                                                         [회고 앱]
collector/collect.py   → data/summaries/<라벨>.json (숫자, 가림)   리포트 · 타임라인
scripts/dump_messages.py → <라벨>.messages.md (가린 내 메시지)
        ↓ Claude Code가 읽고 작성
reports/<라벨>.analysis.json  ──────────────────────────────▶  읽기
reports/<라벨>.me.json  ◀── 👍/👎 · 목표 · 한 줄 (자동 저장) ──  누르기
```

- 원본 대화는 PC 밖으로 나가지 않습니다. `reports/`, `data/summaries/`, `config.local.json`은 커밋되지 않습니다.
- 내 리포트가 없는 환경(배포판)에서는 `data/sample/sample.analysis.json` 가상 샘플을 보여줍니다.

## 직접 실행 (스킬 없이)

```bash
pip install -r requirements.txt
python collector/collect.py --month 2026-11          # --initial 이면 처음부터 오늘까지
python scripts/dump_messages.py --label 2026-11
# → reports/2026-11.analysis.json 작성 (형식: core/analysis.py 의 EXAMPLE)
python scripts/attach_metrics.py 2026-11
python scripts/check_analysis.py reports/2026-11.analysis.json
python -m streamlit run streamlit_app.py
```

개인 설정 `config.local.json` (`config.example.json` 복사): Claude 기록 폴더, 블로그 `history.json` 경로, 가릴 이름 목록.

## 지표 (리포트 근거용 15개)

| 묶음 | 지표 |
| --- | --- |
| 요청 품질 | 끝난 기준을 붙인 요청 · 계획을 먼저 세운 요청 · 증거를 요구한 요청 · 요구가 4개 이상 섞인 요청 |
| 재작업·막힘 | 다시 고치라는 요청 · 불신·답답함 표현 · 중간에 끊은 횟수 · 사용량 한도 도달 |
| 세션 관리 | 세션당 메시지 · 긴 세션 · 3일 넘게 이어진 세션 · 15자 이하 짧은 지시 |
| 이해·학습 | 설명·이유를 물은 메시지 · 점검·검증 요청 · 에러를 그대로 붙여넣은 횟수 |

키워드 규칙(`core/metrics.py`)이라 방향을 보는 용도입니다. 잘못 잡힌 문장은 `data/rules_override.json`에 `{"지표키": ["제외할 문장 일부"]}`.

## 민감정보

`core/redact.py`: API 키(sk-, AIza, ghp_ 등), `.env` 형식 비밀번호·토큰 줄, 이메일, IP, 사용자 폴더 경로, 지정한 이름을 가립니다.
수집기와 `check_analysis.py`가 한 번 더 검사합니다.

## 폴더 구조

```
collector/collect.py        숫자 수집 (내 PC 전용)
scripts/dump_messages.py    분석용 메시지 모음
scripts/attach_metrics.py   리포트에 숫자 붙이기
scripts/check_analysis.py   형식·민감정보 검사
core/                       claude_logs · github_activity · blog · metrics · redact · analysis · ui
streamlit_app.py, app_pages/ 리포트 · 타임라인 · 만드는 법
docs/monthly-ai-report.SKILL.md  Claude 스킬 사본 (~/.claude/skills/monthly-ai-report/)
data/sample/                배포 데모용 가상 리포트
tests/                      pytest
```

## 로드맵

- [x] 수집기 · Claude 분석 스킬 · 리포트/타임라인 앱 · 0회차 초기 총정리
- [ ] 👍 받은 리포트를 티스토리에 자동 게시 (주간회고 프로그램 방식, 게시 전 민감정보 재검사)
- [ ] 매달 1일 알림 (Windows 작업 스케줄러)

## 테스트

```bash
python -m pytest -q
```
