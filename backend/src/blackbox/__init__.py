"""블랙박스 사건 (docs/design-blackbox.md)

  analyzer.py  분석기 빈자리: 규약, get_analyzer(), 출력 검사 validate_output() (1절)
  fake.py      가짜 분석기, scenarios/ 시나리오 JSON (2절)
  sync.py      영상 촬영 시각 추정, 차량 기록 구간, 시각 맞추기 (fine / coarse / none, 5절)
  merge.py     user > vehicle > video > default 합치기, source_conflicts (4절)
  adapter.py   질문·판정·남은 질문 (src/vehicle/adapter.py 재사용)
  evidence.py  판정에 쓴 답의 근거 문장
  store.py     bb_cases 표
  api.py       POST·GET·PUT answers·DELETE /api/bb-cases, 분석 스레드 (3절)

MTM에서 가져온 코드(src/app, src/analyze, src/server, judge)와 src/vehicle/rules.py는 고치지 않고 불러 쓰기만 한다.
"""
