# A(영상 분석·질문)에게 보내는 요청 (B → A)

B 판정 모듈(judge)이 읽는 사실값과 A가 묻고 넘기는 값이 맞지 않는 곳. B 쪽에서 이름·값만 바꿔 해결되는 것은
`adapter.py`에서 바꾸고(아래 "B에서 처리함"), 질문 자체를 바꿔야 하는 것만 여기 적는다.

## hmtm-0.1.1 (2026-11-09) 보행자·자전거 질문 (`backend/src/app/chapters.py`)

### B에서 처리함 (A는 할 일 없음)

| A 답 | B가 읽는 값 |
|---|---|
| `crossing_place = on_crosswalk` | `ped_place = crosswalk` (보행자 당사자만) |
| `crossing_place = near_crosswalk` | `ped_place = near_crosswalk` (보행자 당사자만) |
| `ped_signal_at_crossing = green_flashing` | `ped_signal_at_crossing = flashing_green` (B의 신호 값 이름) |

### 요청 1. 보행자 신호를 "횡단 시작 때"와 "부딪힐 때" 둘로 물어 주세요

- 지금: `parties.<id>.ped_signal_at_crossing` 하나 (`green` / `green_flashing` / `red`)
- B가 읽는 값: `ped_signal_at_start`, `ped_signal_at_impact` (값 `green` / `flashing_green` / `red`)
- 이유: 신호 있는 횡단보도 도표(보1~보12, 보14~보19)는 두 시점의 신호 조합으로 갈린다.
  예) 보1 = 적색 시작·적색 충격(30:70), 보3 = 적색 시작·녹색(점멸) 충격(70:30), 보11(가) = 녹색 시작·적색 충격(90:10).
  하나의 답을 B가 두 값에 똑같이 넣으면 "녹색에 건너기 시작해 적색에 부딪힘" 같은 경우를 틀리게 판정하므로 B는 나누지 않는다.
- 제안: 질문 두 개 (`ped_signal_at_start` "건너기 시작할 때 보행자 신호는?", `ped_signal_at_impact` "부딪힐 때 보행자 신호는?").
  보기 값은 B 이름(`flashing_green`)으로. 조건(`depends_on`)은 지금과 같게.
- 차53-1(이륜차 등이 횡단보도로 건넌 사고)은 `ped_signal_at_crossing == red`를 읽는다. 두 질문으로 바꾸면 `ped_signal_at_crossing`은
  `ped_signal_at_impact`와 같은 값으로 넘겨 주세요 (`answers.to_assumptions`).

### 요청 2. "부딪힌 곳" 보기 두 개를 나눠 주세요

| 지금 보기 | B 값 후보 | 갈리는 도표 |
|---|---|---|
| `carriageway` (횡단보도 없는 차도) | `intersection`(신호 없는 교차로 횡단) / `road`(단일로 횡단) / `roadway`(차도를 따라 걷던 중) | 보22 / 보23 / 보25~보28 |
| `sidewalk` (보도·길 가장자리) | `sidewalk`(보도) / `roadway` + `roadway_walk_position = edge`(보도 없는 길 가장자리) | 보24 / 보27-2 |

- B는 두 보기를 추측해서 바꾸지 않고 `ped_place`를 비워 둔다 (판단 보류). 그래서 지금은 이 답으로 고르는 도표가 없다.
- 제안: 보기를 B 값에 맞춰 늘리거나, 질문 필드를 `ped_place`로 바꾸고 B 값을 그대로 보기로 쓰기.
  B 값 전체: `crosswalk`, `near_crosswalk`, `near_overpass`(육교·지하도 부근, 보21), `intersection`, `road`, `sidewalk`, `roadway`,
  `ped_only_road`(보행자 전용도로, 보29-1), `ped_priority_road`(보행자 우선도로, 보29-2). 정의는 `FACTS_SPEC.md` 3-15.
- 자전거·농기계 당사자: B의 자전거 도표는 `ped_place`를 읽지 않는다. 자전거는 `on_bike_crossing`(자전거횡단도), `crossing_road`(도로 횡단),
  `bike_lane_type` 등을 쓴다 (`FACTS_SPEC.md` 3-16). 자전거에게는 다른 질문이 필요하다.

### 요청 3. `CHAPTER_OF`에 `person`을 넣어 주세요

- 지금: `CHAPTER_OF = {"pedestrian": ..., "bicycle": ..., "farm_machine": ...}`
- 블랙박스 분석기 계약(`src/blackbox/analyzer.py`의 `CLASSES`)은 보행자를 `person`으로 낸다. B는 `person`과 `pedestrian`을 둘 다 보행자로 본다.
- 영향: 블랙박스 사건에서 상대가 `person`이면 A는 자동차 장으로 보고(`chapters.chapter`가 `vehicle`) 차대차 질문(`situation.py`)을 낸다.
  B는 차대보행자로 판정하므로 질문과 판정이 어긋난다.
- 제안: `"person": "pedestrian"` 추가.

### 같이 고칠 문서·주석

- `chapters.py` 맨 위 설명: "rules_vehicle.json", "지금은 자전거·보행자 사고도 자동차끼리 도표로 판정됨"은 hmtm-0.1.0부터 맞지 않음
  (차대차 파일은 `rules.json`, 보행자·자전거 도표 있음)
- `docs/engine/app_io.md`, `docs/engine/A_pipeline.md`의 `crossing_place`·`ped_signal_at_crossing` 설명

## hmtm-0.1.1 (2026-11-10) A가 아직 만들지 않는 보행자·자전거 필드

`rules_pedestrian.json`, `rules_bicycle.json`이 읽는 필드 중 지금 A의 영상 분석(`src/analyze/build_facts.py`, 블랙박스 분석기 계약
`src/blackbox/analyzer.py`)이나 질문(`src/app/chapters.py`) 어디서도 만들지 않는 것. 각 파일의 `facts_used` 설명이 아니라
도표 조건(`applies_when`)과 그 도표가 참조하는 수정요소(`modifiers.json` + 유형별 사전)의 `fact`를 모두 뽑아 정리했다.

- **도표 선택용**: 도표 조건에 있다. 비어 있으면 그 도표가 판단 보류라 비율 자체가 안 나온다. 먼저 채워야 한다.
- **수정요소 전용**: 가감에만 쓴다. 비어 있으면 그 가감만 "확인 필요"로 남고 기본 비율은 나온다.
- **채울 곳**: 영상 = 지금 궤적·영역으로 계산 가능, 모델 = 새 인식 모델이나 장면 영역(횡단보도·정지선·자전거도로) 필요,
  질문 = 사용자 답. 여럿이면 앞이 우선, 뒤가 대안. 정의는 `FACTS_SPEC.md` 3-15, 3-16.
- **차대차 질문에만 있음**: `situation.py`가 묻는 필드지만, `situation.questions`는 보행자·자전거 장에서 질문을 내지 않으므로
  (`chapters.chapter(...) != "vehicle"`이면 `[]`) 이 사고들에서는 아무도 만들지 않는다. 질문 문구는 있으니 장 조건만 풀면 된다.
- 블랙박스 사건(`src/blackbox/adapter.py`)은 `chapters.questions`를 부르지 않아 `crossing_place`·`ped_signal_at_crossing`도 묻지 않는다.

### 1. 도표 선택용

#### 차대보행자 (보1~보36)

| 필드 | 값 | 갈리는 도표 | 채울 곳 |
|---|---|---|---|
| `dist_from_crosswalk_m` | m | 보14~보21: `ped_place = near_crosswalk`(보21은 `near_overpass`) **이고 30m 이하**. 30m 초과면 보22·보23 | 모델 + 질문 |
| `ped_signal_at_start`, `ped_signal_at_impact` | `green` / `flashing_green` / `red` | 보1~보12, 보14~보19 (위 요청 1) | 모델 + 질문 |
| `ped_place` (남은 값) | `near_overpass`, `intersection`, `road`, `sidewalk`, `roadway`, `ped_only_road`, `ped_priority_road` | 보21~보29 (위 요청 2). 지금은 `crosswalk`·`near_crosswalk`만 만들어짐 | 모델 + 질문 |
| `crosswalk_signal` (장소) | true / false | 보1~보19(신호 있음) vs 보13·보20(없음) | 모델 + 질문 |
| `impact_after_intersection` | true / false | 보1~보7(교차로 통과 후) vs 보8~보12(통과 전) | 영상 (교차로 영역) |
| `passed_crosswalk` | true / false | 보14~보18(횡단보도 통과 후) vs 보19(통과 전) | 모델 (횡단보도 영역) |
| `right_turn_signal` | `green` / `red` / `none` | 보17, 보18 (우회전 신호기) | 모델 + 질문 |
| `ped_activity` | `crossing` / `walking` / `lying_or_playing` | 보23(횡단), 보27-1·보27-2·보28(차도 보행), 보30(누움·놀기) | 영상 (누움은 모델) + 질문 |
| `crossing_road_width` | `narrower` / `equal` / `wider` | 보22 (신호 없는 교차로에서 건넌 도로 폭) | 질문 |
| `roadway_walk_position` | `edge_1m` / `beyond_1m` / `edge` / `center` | 보26, 보27-2, 보28 | 모델 + 질문 |
| `sidewalk_separated` (장소) | true / false | 보25·보26(구분 있음) vs 보27-1~보28(없음) | 모델 + 질문 |
| `sidewalk_closed` | true / false | 보25 vs 보26 (보도 공사로 차도 보행) | 질문 |
| `riding_on_crosswalk` | true / false | 보33 (이륜차가 횡단보도를 타고 건넘) | 모델 + 질문 |
| `expressway_walk_reason` | `none` / `justified` | 보35 vs 보36 | 질문 |
| `road_class = expressway` (장소, 값만) | | 보35, 보36. 필드는 `road.center_line` 답으로 `general`/`side_street`만 만들어짐 | 질문 |

**횡단보도 거리는 도표가 4구간을 쓴다.** 거리 하나가 도표 선택과 수정요소에 함께 쓰이므로, 질문으로 받을 때도 이 4구간을 보기로 둬야 한다.

| 구간 | B 값 | 적용 |
|---|---|---|
| 횡단보도 위 | `ped_place = crosswalk` | 보1~보13 |
| 10m 이내 (부근) | `ped_place = near_crosswalk`, `dist_from_crosswalk_m` ≤ 10 | 보14~보20 (육교·지하도 부근은 `near_overpass`, 보21) |
| 10~30m | `ped_place = near_crosswalk`, 10 < `dist_from_crosswalk_m` ≤ 30 | 같은 도표 + 수정요소 `ped_near_10_30m` (보행자 +10) |
| 30m 초과 | `ped_place = near_crosswalk`(또는 `near_overpass`), `dist_from_crosswalk_m` > 30. 또는 `ped_place = intersection` / `road` | 무단횡단 기준 보22(교차로)·보23(단일로) |

- 지금 "횡단보도 부근" 답은 `ped_place = near_crosswalk`로만 가고 거리가 비어서, 보14~보21의 `dist_from_crosswalk_m <= 30` 조건이 판단 보류로 남는다.
- 제안: `crossing_place` 보기를 "횡단보도 위 / 횡단보도에서 10m 이내 / 10~30m / 30m 넘게 떨어진 곳"으로 나누고,
  `dist_from_crosswalk_m`에는 구간 대표값(10m 이내 → 5, 10~30m → 20)을 넣는다. 정확한 거리를 잴 수 있으면(모델) 그 값을 우선.
  30m 초과는 `near_crosswalk` + 대표값(예: 40)으로 넘기면 보22·보23 조건에 맞는다 (둘은 `crossing_road_width`·`ped_activity`와 장소로 갈림).
  거리 구간을 모르면 거리를 비워 둔다 (보14~보23 모두 판단 보류, 추측하지 않음).
- 육교·지하도도 같은 거리 필드를 쓴다 (`rules_pedestrian.json`의 보21 메모).

#### 차대자전거 (거1~거43)

| 필드 | 값 | 갈리는 도표 | 채울 곳 |
|---|---|---|---|
| `crossing_road` | true / false | 거41 (도로 횡단), 거33-2와 구분 | 영상 + 질문 |
| `on_bike_crossing` | true / false | 거42 (자전거횡단도) | 모델 (횡단도 영역) + 질문 |
| `bike_lane_type` | `dedicated_road` / `dedicated_lane` / `priority_road` / `none` | 거43 | 질문 (모델 가능) |
| `approached_right_edge` | true / false | 거10 (우회전 전 우측 끝으로 다가섬) | 영상 + 질문 |
| `stop_sign` | true / false (당사자별) | 한쪽 일시정지 표지 도표 | 질문 — 차대차 질문에만 있음 (`road.stop_sign_side`) |
| `unprotected_left_sign` | true / false | 비보호 좌회전 도표 | 질문 — 차대차 질문에만 있음 |
| `one_way_violation`, `wrong_way`, `from_off_road` | true / false | 일방통행 역진입·역주행·도로 외 진입 도표 | 질문 — 차대차 질문에만 있음 (`situation.special`) |

### 2. 수정요소 전용

#### 차대보행자

| 필드 | 쓰이는 곳 | 채울 곳 |
|---|---|---|
| `vulnerable_type` | 어린이·노인·장애인 감산 | 질문 |
| `protection_zone` (장소), `in_own_protection_zone` | 보호구역 감산 (어린이 감산과 하나만) | 질문 (표지 인식은 모델) |
| `ped_factors` | 집단 횡단, 갑자기 뛰어듦, 고의 막기, 인라인스케이트 | 영상(집단·뛰어듦) + 모델 + 질문 |
| `walk_manner` | 멈춤·되돌아감·갈지자 보행 | 영상 |
| `diagonal_crossing` | 비스듬히 횡단 | 영상 |
| `opposite_side_start` | 반대편에서 횡단 시작 | 영상 |
| `inside_stop_line` | 정지선 안쪽 횡단 | 모델 (정지선 영역) |
| `passed_stopped_vehicles` | 정지 차량 옆을 지나 통과 | 영상 |
| `behind_before_reverse`, `reverse_warning` | 후진 사고 (보32) | 영상 / 질문 |
| `ped_posture` | 보30 앉아 있음·누움 | 모델 |
| `on_shoulder` | 고속도로 갓길 (보36) | 모델 + 질문 |
| `arterial_road`, `ped_busy_area`, `vehicle_access_zone`, `bright_place` (장소) | 간선도로 가산, 주택·상점가 감산, 차량 출입 장소 가산, 밝은 곳 감산 | 질문 |
| `crossing_prohibition` (장소) | 횡단금지 표지 +10·시설 +20 | 모델 + 질문 |
| `bad_weather`, `easy_walk_area`, `ped_warning_sign` (장소) | 고속도로 악천후, 보행이 쉬운 곳, 보행자 주의 표지 (보35·보36) | 질문 (악천후는 모델 가능) |
| `view_obstructed` (장소) | 시야장애 가산 (야간과 하나만) | 질문 — 차대차 질문에만 있음 (`situation.special`) |
| `user_factors`, `speed_over_limit_kmh` (자동차) | 운전자 현저·중대한 과실, 이 장은 10km/h 이상부터 | 질문 — 차대차 질문에만 있음 (`driver_factors`). 블랙박스 내 차 속도는 차량 기록 + 제한속도로도 가능 |
| `avoidable_at_limit` (자동차) | 속도위반의 인과관계 | 질문 (차대차에서도 아직 안 만듦) |

`night`는 블랙박스 분석기 계약(`road.night`)에만 있고 CCTV 분석·질문에는 없다 (차대차 `situation.special`에만 있음).

#### 차대자전거

| 필드 | 쓰이는 곳 | 채울 곳 |
|---|---|---|
| `vulnerable_type` | 어린이·노인·장애인 감산 | 질문 |
| `bike_lane_nearby`, `in_bike_lane` | 자전거도로 부근 차도 통행 가산, 자전거도로 안 감산 (하나만) | 모델 + 질문 |
| `left_side_riding` | 도로 왼쪽 통행 가산 | 영상 |
| `diagonal_crossing` | 비스듬히 횡단 | 영상 |
| `path_blocked`, `obstacle_ahead` | 진로 막힘, 앞 장애물 감산 | 모델 + 질문 |
| `foresee_lane_change` | 거43 자동차 진로변경 예상 가능 | 질문 |
| `lanes_two_plus`, `dashed_bike_lane_border` (장소) | 거41 2차로 이상, 거43 점선 경계 | 모델 + 질문 |
| `user_factors` (자전거) | 음주·과적·야간 무등화·한 손·휴대전화·안전모 미착용 등 | 질문 (`no_helmet`은 모델 가능) |
| `user_factors` (자동차, `drowsy` 포함), `speed_over_limit_kmh` | 자동차 현저·중대한 과실 | 질문 — 차대차 질문에만 있음 (`driver_factors`, `drowsy` 보기는 없음) |
| `sudden_lane_change`, `forbidden_lane_change`, `brake_light_failure`, `sudden_stop_without_reason`, `turn_almost_completed` | 진로변경·급정지·좌회전 거의 끝냄 | 질문 — 차대차 질문에만 있음 (`situation.special`) |
| `view_obstructed` (장소) | 시야장애 가산 | 질문 — 차대차 질문에만 있음 |
| `off_right_side` | 오른쪽 통행 불이행 (공통 사전) | 영상 + 질문 (차대차에서도 아직 안 만듦) |
| `entry_speed_to_limit` | 서행·일시정지 위반 (공통 사전) | 영상 (실속도 km/h + 제한속도 필요, 지금은 화면 비율 속도만) |
| `avoidable_at_limit` | 속도위반의 인과관계 | 질문 (차대차에서도 아직 안 만듦) |

### 이미 만들어지는 값 (참고)

두 파일이 읽는 나머지는 A가 만든다: `cls`, `movement`(`reverse`·`lane_change` 포함), `signal_at_entry`, `lead_order`,
`started_after_stop`, `stopped_before_entry`, `entry_speed`·`entry_speed_ratio`·`entry_lead_sec`(영상), `on_wider_road`·`road_width`
(`road.wider_road` 질문), `scene.location`, `signal.state`, `scene.center_line`, `turn_signal_used`(블랙박스 분석기·차량 기록).
