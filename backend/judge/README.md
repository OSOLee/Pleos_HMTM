# MTM 규칙 판정 (B)

facts.json(A의 영상 분석 결과)에 「자동차사고 과실비율 인정기준」(2023.06.30 개정판)을 적용해 예상 과실비율과 근거를 낸다.

## 버전

현재 버전은 `VERSION` 파일, 변경 내역은 `CHANGELOG.md`에 있다. 판정 결과에도 `engine_version`이 기록된다.

## 구성

| 파일 | 역할 |
|---|---|
| `run_judge.py` | 실행 진입점. facts.json → result.json |
| `adapter.py` | A의 facts(0.2/0.3) → 엔진 형식 변환 |
| `fault_engine.py` | 규칙 엔진 (도표 선택, 역할 배정, 수정요소 적용, 중복 규칙) |
| `rules.json` | 도표 124개 (변형 포함): 제3편 제2장 차대차 사고 전체 (교차로 차1~21, 마주보는 방향 차31~33, 같은 방향 차41~48, 기타 차51~55, 이륜차 특수 차61) |
| `rules_pedestrian.json` | 도표 45개: 제3편 제1장 차대보행자 사고 (보1~보36). A = 자동차, B = 보행자 |
| `rules_bicycle.json` | 도표 55개: 제3편 제3장 차대자전거(농기계 포함) 사고 (거1~거43). A = 자전거, B = 자동차 |
| `modifiers.json` | 수정요소 사전 (현저·중대한 과실, 사고상황별, 기타). 정의, 기본 가감, 판단 방법. 모든 유형이 같이 씀 |
| `modifiers_pedestrian.json`, `modifiers_bicycle.json` | 유형별 추가 수정요소 사전 (보행자·자전거 고유 항목, 장별 속도위반·졸음운전 기준) |
| `assumptions/<영상>.json` | 영상에서 알 수 없는 장소 정보의 임시 가정 (체크리스트가 생기면 대체) |
| `docs/FACTS_SPEC.md` | A에게 요청하는 facts.json 필드 명세 |
| `docs/RULES_INDEX.md` | 전체 도표 목록, 원문 대조 체크리스트 |
| `docs/A_REQUESTS.md` | A(영상 분석·질문)에게 보내는 요청. B에서 이름만 바꿔 해결할 수 없는 것 |
| `tests/` | 단위 테스트 |

## 사고 유형

엔진이 충돌 당사자(`collision.between`)의 차종(`cls`)으로 사고 유형을 정하고 해당 규칙 파일을 쓴다. 사용자에게 사고 유형을 묻지 않는다. 수정요소는 공통 사전 `modifiers.json`에 유형별 추가 사전을 합쳐 쓴다.

| 유형 (`accident_category`) | 당사자 | 규칙 파일 | A | B | 비율 표기 |
|---|---|---|---|---|---|
| `car_car` | 자동차·이륜차끼리, 또는 차종 모름 | `rules.json` | 도표별 | 도표별 | 원문 그대로 |
| `car_pedestrian` | 사람(`person`, A의 `pedestrian`)이 있음 | `rules_pedestrian.json` | 자동차 | 보행자 | 원문은 보행자 과실만 표기. A = 100 − 보행자 과실 (보35·보36은 원문 A·B를 바꿔 넣음) |
| `car_bicycle` | 자전거·농기계(`bicycle`, `farm_machine`)가 있음 | `rules_bicycle.json` | 자전거 | 자동차 | 원문 A:B 그대로 |

- 자전거와 보행자 사이의 사고는 인정기준의 자동차 사고 도표 범위 밖이라 판정하지 않는다 (`supported: false`).
- 화면에 보행자가 있어도 충돌 당사자가 아니면 차대차로 판정한다.
- 보행자 장과 자전거 장은 자동차의 제한속도 위반이 10km/h 이상부터 현저한 과실이라 장별 사전에 따로 있다. 자전거 장은 자동차 졸음운전이 중대한 과실이다.
- 규칙을 직접 넘기면(`judge(facts, rules_doc, catalog)`) 유형을 판단하지 않고 그 규칙만 쓴다. 서비스 코드는 `judge(facts)`로 부른다.
- 판정 결과에 `accident_category`, `accident_category_reason`이 들어간다.

## 실행

```bash
python run_judge.py facts.json
python run_judge.py facts.json --assume 22.movement=right_turn
python run_judge.py facts.json --assume 28.damage_severity=severe -o result.json
```

## 테스트

```bash
python -m unittest discover -s tests -v
```

## 반영된 인정기준 규칙

- 수정요소 가감: 한쪽 가산 시 상대 감산, 0~100% 범위, 합계 100% (총설 p.21)
- 기본 0:100이면 0인 쪽 수정요소 먼저, 상대가 100% 미만일 때만 상대 수정요소 (총설 p.21)
- 현저한 과실 합계 최대 20%, 중대한 과실과 겹치면 중대한 과실만 (총설 p.21)
- 서행·감속 불이행과 속도위반 중복 불가 (p.135)
- 인과관계 없는 위반은 비적용 (총설 p.18~19)
- 이륜차 감산 −5~10 (중대한 과실이면 비적용), 대형차 가산 +5 (이륜차 상대면 비적용) (p.144)
- 사용자 입력으로 적용된 수정요소는 "입증 필요" 표시 (총설 p.20)
- 도표의 "활용시 참고 사항" 중 적용 제외 조건(`exclude_if`): 확인되면 도표 제외, 모르면 주의 문구

## 도표 추가 방법

1. 사고 유형에 맞는 규칙 파일(`rules.json`, `rules_pedestrian.json`, `rules_bicycle.json`)의 `rules`에 도표 항목 추가 (`applies_when`, `base`, `modifiers`)
2. 수정요소는 `modifiers.json`(또는 유형별 사전)의 `id`로 참조하고, 도표에 적힌 값을 `delta`로 지정
3. 사전에 없는 도표 고유 수정요소는 사전에 먼저 추가. 조건(`when`)에 `any`는 쓸 수 없다. 필요하면 항목을 나누고 `exclusive_groups`로 하나만 적용되게 한다
4. 새 fact를 쓰면 `adapter.py`의 `OPTIONAL_PARTY_FIELDS`(당사자) 또는 `SCENE_FIELDS`(장소)에 추가 (`tests/test_adapter_fields.py`가 빠진 이름을 잡는다)
5. `source.verified`는 원문 대조 후 `true`로 변경
6. 테스트에 기본 비율과 참고판례 결과를 확인하는 케이스 추가

## 주의

- AI Hub 데이터와 영상은 재배포 금지라 저장소에 올리지 않는다 (`.gitignore`).
- 결과는 참고용이며 법적 효력이 없다.
