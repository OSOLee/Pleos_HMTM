# 결과 고정 시험 (golden)

리팩토링 전 "지금 동작"을 고정해 둔 시험이다 (태그 `v0.9-pre-refactor`). 코드를 고쳐도 서버 응답이 저장한 것과 같아야 한다.

| 파일 | 내용 |
|---|---|
| `cases.py` | 사건 정의(`DEMO`, `VEHICLE`)와 만들기·정리·비교 |
| `test_golden.py` | 지금 응답 ↔ `data/<사건>.json` 비교. 다르면 다른 칸을 모두 보여 줌 |
| `save.py` | 기준 응답 다시 저장 (결과를 일부러 바꿨을 때만) |
| `data/*.json` | 사건마다 `{단계: 응답}` |

## 무엇을 만드나

- **데모 사건**: `android/tools/sd_data.py`의 `DEMO_SCENARIOS` 일곱 개(가짜 분석기, 30초 영상) + 차량 기록 없는 것 둘.
  차량 기록은 `sd_data.py`가 에뮬레이터에 넣는 루프 CSV와 같은 값을 앱처럼 영상 구간 ±15초로 잘라 보낸다.
- **차량 사건 API**(`/api/vehicle-cases`): 우회전 지시등, 직진 서행 동시 진입, 후진.
- 단계: `post`(분석 뒤 첫 응답) → 정해진 답(`PUT answers`) 또는 사고 순간 고르기(`PUT collision`, 첫 후보) → `get`.
  `get`이 마지막 단계와 같으면 `"= <단계>"`로만 적는다.
- 응답 전체를 저장한다 (과실비율·도표·answers와 근거 문장·remaining·vehicle_effects·source_conflicts·collision_review·질문 등).
  빼는 칸: 맨 위 `id`·`created_at`·`updated_at`·`judge_version`, `sync.params`(설정 상수).
  서버 시각은 고정(블랙박스: 촬영 1분 뒤, 차량 사건: 사고 1분 뒤). `HMTM_BB_ANALYZER`와 상관없이 fake로 돈다.

## 명령 (`backend/`에서)

```powershell
.venv\Scripts\python -m pytest tests\golden              # 비교
.venv\Scripts\python tests\golden\save.py                # 전부 다시 저장 (바뀐 칸을 보여 줌)
.venv\Scripts\python tests\golden\save.py no_collision_pick vehicle_reverse   # 몇 사건만
.venv\Scripts\python tests\golden\save.py --list         # 사건 이름
```

- 결과를 **일부러** 바꾼 PR에서만 다시 저장하고, `git diff tests/golden/data`로 바뀐 칸이 의도한 것인지 확인한 뒤 같이 커밋한다.
- 리팩토링 PR에서는 다시 저장하지 않는다. 시험이 깨지면 동작이 바뀐 것이다.
- 사건을 더하거나 빼면 `cases.py`를 고치고 `save.py`를 돌린다 (`test_same_cases`가 파일과 정의가 맞는지 본다).
