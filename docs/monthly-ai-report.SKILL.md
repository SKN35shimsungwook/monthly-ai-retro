---
name: monthly-ai-report
description: 사용자의 월간 AI 활용 회고 리포트를 만든다. "월간 리포트 만들어줘", "초기 총정리 리포트", "N월 AI 회고 리포트" 같은 요청에 사용. Claude Code 기록·GitHub·주간회고를 수집하고, 그 달 내 메시지를 전부 읽어 요약·사용 유형·강점·약점·보완점·변화·나라는 사람을 근거와 함께 써서 monthly-ai-retro/reports/에 저장한다.
---

# 월간 AI 활용 리포트 만들기

프로젝트: 이 저장소(`monthly-ai-retro`) 폴더 (모든 명령은 이 폴더에서, `PYTHONIOENCODING=utf-8`).
기준 예시: `reports/0-initial.analysis.json` — 이 깊이와 말투를 맞춘다. 형식은 `core/analysis.py`의 `EXAMPLE`.

## 1. 기간 정하기
- "초기 총정리" → `--initial`, 라벨 `0-initial`
- "N월" → `--month YYYY-MM`, 라벨 `YYYY-MM`
- 말이 없으면 지난달. 이미 `reports/<라벨>.analysis.json`이 있으면 덮어쓸지 먼저 묻는다.

## 2. 수집
```bash
python collector/collect.py --month 2026-11
python scripts/dump_messages.py --label 2026-11
```
`data/summaries/<라벨>.json`(숫자)과 `<라벨>.messages.md`(가린 내 메시지 전부)가 생긴다.

## 3. 읽기 — 건너뛰지 말 것
- `<라벨>.messages.md`를 **처음부터 끝까지** 읽는다(길면 나눠서). 숫자만 보고 쓰지 않는다.
- 요약 json의 지표 15개와 세션 목록, GitHub, 블로그를 함께 본다.
- 직전 리포트(`reports/` 안의 바로 앞 라벨 analysis.json)와 그 `.me.json`(사용자가 👍/👎 한 항목, 고른 목표)을 읽는다.
  - 👎 받은 관찰은 같은 근거로 반복하지 않는다. 고른 목표는 이번 숫자로 확인해 `change`에 넣는다.

## 4. 쓰기 — `reports/<라벨>.analysis.json`
- 모든 강점·약점은 **실제 대화 근거**(짧은 인용이나 숫자)를 `evidence`에 넣는다. 인용은 15단어 이내, 민감정보·팀원 이름 금지.
- 4D(위임·설명·분별·책임) 중 하나를 `d4`에 단다.
- `recommendations.better`는 사용자가 그대로 복사해 Claude에게 보낼 수 있는 한국어 요청 문장.
- `change`: 월간이면 지난 리포트 대비(지표 + 습관 + 지난 목표 달성 여부). 초기 총정리면 기간 초반 대비 최근.
- `person`: 기술적·일하는 방식·배우는 방식·사회적·동기와 진로. 진단이 아니라 관찰. 희망 직무(기술영업·AX 컨설턴트)와 연결.
- `goal_candidates` 3~4개: 반드시 `core/metrics.py`에 있는 지표 키 + 현실적인 목표값 + "지금 값" 포함 문장.
- 말투: 문서는 "~다" 체, 짧은 문장, 쉬운 말. 칭찬만 하거나 깎아내리지 말고 근거로 말한다.
- `limits`에 이 분석의 한계를 적는다.

## 5. 마무리
```bash
python scripts/attach_metrics.py 2026-11
python scripts/check_analysis.py reports/2026-11.analysis.json
```
검사가 OK일 때까지 고친다. 그다음 사용자에게 한국어로 알린다:
- 이번 달 한 줄 결론과 가장 큰 변화 2~3개
- "회고 앱(회고앱_실행.bat)에서 읽고 👍/👎와 목표만 골라 주세요"

`reports/`와 `data/summaries/`는 커밋하지 않는다(.gitignore).
