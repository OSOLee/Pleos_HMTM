# 시험

파이썬 기본 `unittest`만 써서 따로 설치할 것은 없다. MTM 폴더에서 돌린다.

| 명령 | 내용 | 시간 |
|---|---|---|
| `python -m unittest tests.test_units` | 함수 단위 시험. 지금까지 고친 버그(진입 전 정지, 흔들림 보정, 정답 경로, 답 검사 등)가 다시 생기지 않는지 | 몇 초 |
| `python -m unittest tests.test_inputs` | 이상한 모서리·답 입력을 넣어도 파이썬 오류 없이 한국어 안내로 끝나는지 | 1분 |
| `MTM_SLOW=1 python -m unittest tests.test_inputs` | 위 + 처음 보는 영상(깨진 파일, 1프레임, 차 없는 화면, 세로 영상, 달리는 블랙박스) | 10분 |
| `python -m unittest tests.test_rules_coverage` | A 형식 facts + 답을 B 판정 모듈에 넣어 차대차 도표(일시정지 표지, 추돌, 진로변경, 역주행, 앞지르기, 유턴, 바닥 화살표)가 골라지는지 | 1초 |
| `python -m unittest tests.test_pipeline` | `src/app/pipeline.py`를 서버처럼 직접 부를 때 순서가 틀리면(모서리 없이 판정 등) 알맞은 오류 코드가 나는지 | 몇 초 |
| `MTM_SLOW=1 python -m unittest tests.test_pipeline` | 위 + 모서리 먼저 → 탐지 → 판정까지 돌려 저장된 자동 결과와 같은지 | 1분 |
| `MTM_SLOW=1 python -m unittest tests.test_eval` | 평가 24개를 임시 폴더에서 다시 돌려 결과표 숫자가 기준 아래로 떨어지지 않는지 | 10분 |
| `python -m unittest discover tests` | 빠른 것 전부 (느린 것은 건너뜀) | 1분 |

- `test_inputs`, `test_eval`은 git에 없는 영상(`data/videos`)과 평가 결과(`outputs/eval_*`)를 쓴다. 없으면 건너뛴다
- 코드를 고친 뒤에는 빠른 것을, 충돌·장면·판정 연결을 고쳤으면 `test_eval`까지 돌린다
- 평가 숫자가 좋아지면 `test_eval.py`의 `BASELINE`을 올려 둔다
