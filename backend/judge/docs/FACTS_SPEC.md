# facts.json v0.3 명세 (A → B)

A(영상 분석)가 만들고 B(규칙 판정)가 읽는 facts.json의 필드 정의다. 판정 엔진(`adapter.py`)은 0.2와 0.3을 모두 읽으므로, **아래 필드는 한 번에 다 만들 필요 없이 우선순위대로 하나씩 추가**하면 된다. 추가한 만큼 "확인 필요" 항목이 줄어든다.

## 원칙

- **모르는 값은 추측하지 않는다.** 판단하지 못한 값은 `null`로 두고 `unknowns`에 질문으로 남긴다.
- **판정에 쓰는 값은 값 객체로 감쌀 수 있다.** 감싸지 않은 값도 읽는다.
  ```json
  "movement": {"value": "right_turn", "source": "model", "evidence_frame": 108}
  ```
  `source`는 `model`(영상 분석) 또는 `user`(체크리스트 답). `user` 값으로 적용된 수정요소에는 결과에 "입증 필요"가 붙는다.
- **단위를 지킨다.** 시각은 초(`t`)와 프레임(`frame`)을 함께, 속도는 화면 비율 단위와 km/h를 구분한다.

## 1. 최상위

| 필드 | 타입 | 상태 | 설명 |
|---|---|---|---|
| `schema_version` | string | 변경 | `"0.3"` |
| `video`, `fps`, `scene`, `params` | | 0.2 유지 | 영상 정보, 분석 기준값 |
| `road_type` | string | 0.2 유지 | `no_center_line` 등 |
| `road` | object | **추가** | 장소 정보. 아래 2번 |
| `collision` | object | 0.2 유지 | `frame`, `t`, `a`, `b`, `zone`, `pos`, `contact` |
| `parties` | object | 0.2 + 추가 | 당사자별 사실. 아래 3번 |
| `events` | array | 0.2 + 추가 | 교차로 진입 이벤트 추가. 아래 4번 |
| `unknowns` | array | **추가** | 체크리스트 질문 목록. 아래 5번 |

## 2. `road` (장소 정보)

1차에는 대부분 **사용자 체크리스트 답**으로 채운다. 2차에 자동 인식으로 바꿔도 필드는 그대로 둔다.

| 필드 | 값 | 쓰이는 곳 | 1차 출처 |
|---|---|---|---|
| `location` | `intersection` / `straight`(교차로가 아닌 단일로) / `off_road` | 도표 선택 (교차로 vs 도로가 아닌 장소 진입 등) | 사용자 |
| `junction_type` | `cross` / `t` | 사거리·삼거리 도표 구분 | 사용자 |
| `road_width` | `equal` / `different` | 동일폭 vs 대로·소로 도표. 측정이 아니라 "한눈에 상당히 넓은가"로 판단 (대법원 97다14187) | 사용자 |
| `road_class` | `side_street` / `main_road` | 이면도로 도표 | 사용자 (`road_type`으로 추정 가능) |
| `signal_present` | true / false | 신호 있는 교차로 vs 없는 교차로 | 사용자 |
| `signal_mode` | `normal` / `one_side` / `flashing` | 양쪽 신호(차1~4), 한쪽 도로에만 신호(차5~6), 점멸 신호(차1-5, 3-7, 3-8). 고장·점멸만 작동하면 신호 없는 교차로로 봄 | 사용자 |
| `center_line` | true / false | 중앙선 침범 도표 | 사용자 |
| `speed_limit_kmh` | number | 서행·감속 불이행(진입 속도 ÷ 제한속도), 속도위반 | 사용자 |

## 3. `parties.<id>` (당사자별)

### 3-1. 1차 필수 (A가 영상으로 만드는 값)

| 필드 | 값 | 상태 | 쓰이는 곳 |
|---|---|---|---|
| `cls` | `car` / `truck` / `bus` / `two_wheeler` / `bicycle` / `person` | 0.2 있음 (`vehicle`은 `car`로 읽음) | 장 선택, 이륜차 감산, 대형차 가산 |
| `movement` | `straight` / `left_turn` / `right_turn` / `u_turn` / `reverse` / null | 0.2 있음 | 도표 선택, 역할 배정 |
| `entry_from` | `north` / `south` / `east` / `west` (`appr_n` 등도 받음) | **추가** | **그 차가 들어온 진입로의 방위.** 두 차 모두 있으면 엔진이 화면 방향 벡터 대신 이 값으로 좌우·맞은편·같은 방향을 판단 (원근·어안 왜곡 영향 없음). 방위 기준은 scene.json에서 영상마다 한 번 정함 |
| `heading_start`, `heading_before_collision` | [dx, dy] | 0.2 있음 | 좌우 관계 판단의 대체 수단 (`entry_from`이 없을 때) |
| `origin_zone`, `enter_road` | | 0.2 있음 | 측면 진입로 판단 |
| `approach_speed` | 화면 비율/프레임 | 0.2 있음 | 속도 비율 |
| `intersection_entry` | `{"frame", "t"}` | **추가** | **명확한 선진입**(진입 시간 차이), 신호 사고 |
| `intersection_entry_speed` | 화면 비율/프레임 | **추가** | **서행·감속 불이행**은 교차로 진입 순간 속도로 판단 (p.135). 지금은 충돌 직전 속도로 대체 중 |

### 3-2. 1차 있으면 좋음 (궤적으로 판단 가능)

| 필드 | 값 | 쓰이는 수정요소 |
|---|---|---|
| `wide_turn` / `narrow_turn` | true / false | 넓게(대)·좁게(소) 좌·우회전 (+5~10) |
| `off_right_side` | true / false | 오른쪽 통행 불이행 (차14-1 등, +10) |
| `sudden_turn` | true / false | 급 좌·우회전 (+10). 직진차가 가까이 있을 때 급히 회전 시작 |
| `unsafe_distance` | true / false | 안전거리 확보 위반 (+10) |
| `body_partly_out_waiting` | true / false | 차체를 내밀고 대기 (−10). 도로가 아닌 곳에서 나올 때 차체 일부만 차도에 내민 경우 |
| `forbidden_lane_change` | true / false | 진로변경·앞지르기·끼어들기 금지 위반 (+10). 차선 인식 필요 |
| `entered_congested_intersection` | true / false | 교차로 꼬리물기 (+10) |

### 3-3. 속도 보정 후 (2차)

| 필드 | 값 | 쓰이는 곳 |
|---|---|---|
| `speed_kmh` | km/h | 속도위반 (현저: 20km 미만 초과 / 중대: 20km 이상 초과) |
| `intersection_entry_speed_kmh` | km/h | 감속 불이행 (제한속도의 절반 전후 기준) |
| `avoidable_at_limit` | true / false | 속도위반의 인과관계: 제한속도였다면 피할 수 있었는가 (총설 p.16) |

### 3-4. 사용자 입력 (A가 아니라 체크리스트가 채움)

영상으로는 알 수 없는 값이다. A는 이 필드를 비워 두고 `unknowns`에 질문만 넣으면 된다.

| 필드 | 값 | 쓰이는 수정요소 |
|---|---|---|
| `user_factors` | 아래 목록의 배열. 해당 없으면 `[]`, 모르면 `null` | 현저·중대한 과실 |
| `damage_severity` | `minor` / `moderate` / `severe` | 이륜차 감산 (경미 0, 중간 −5, 큼 −10. 팀 기준) |
| `turn_signal_used` | true / false | 진로변경 신호 불이행 (+10) |
| `damage_enlarged`, `is_large_relative` | true / false | 대형차 가산 (+5) |

`user_factors` 값: `inattention`(전방주시 위반), `drunk_under_0.03`, `drunk_0.03_plus`, `drugs`, `no_license`, `phone`(휴대전화·영상), `dark_tint`(짙은 썬팅), `group_danger`(공동위험행위), `reckless`(난폭운전)


### 3-5. 신호 있는 교차로 (차1~차6)

신호 색은 **각 차량이 교차로에 진입할 때(정지선 통과 시) 자기 쪽 신호** 기준이다.

| 필드 | 값 | 쓰이는 곳 | 출처 |
|---|---|---|---|
| `signal_at_entry` | `green` / `green_arrow`(녹색 좌회전 화살표) / `yellow` / `red` / `flashing_red` / `flashing_yellow` / `none`(자기 쪽 신호기 없음) | 도표 선택의 핵심 | 모델(신호등이 보일 때) 또는 사용자 |
| `signal_at_collision` | 위와 같음 | 녹색·황색에 들어가 적색에 충돌(차1-2, 2-5, 3-5), 녹색 진입 후 황색 충돌(차2-3) | 모델 또는 사용자 |
| `unprotected_left_sign` | true / false | 자기 쪽에 비보호좌회전 표지가 있는가. 차2-2(신호위반 좌회전) vs 차2-6·4-2(비보호 좌회전) 구분, 차2-6 직진차 감산 | 사용자 |
| `stopped_before_entry` | true / false | 적색점멸 일시정지 여부(차1-5 등 적용 여부), 적색 우회전 일시정지 위반(차4-1) | 모델 |
| `stopped_in_intersection` | true / false | 교차로 안에서 일시정지 중인 차량과의 충돌이면 차1-1 미적용 | 모델 |
| `entered_just_before_red` | true / false | 적신호 직전 진입(차1-3, +10). 멀리서 황색을 보고도 무리하게 진입 | 모델 |
| `lane_marking_violation` | true / false | 노면표시 위반(+10). 좌·우회전 지정차로에서 직진 등 | 모델(차선 인식) |
| `turn_almost_completed` | true / false | 좌회전 완료 직후(기 좌회전, −10) | 모델 |
| `lane_change_after_turn` | true / false | 회전 직후 차로 변경(+10) | 모델 |
| `view_obstructed` | true / false | 직진차 시야 제한(차2-6, −10) | 사용자 |
| `entered_congested_intersection` | true / false | 교차로 꼬리물기(+10). 영상으로 명확히 확인될 때만 | 모델 |
| `ped_signal_green_at_turn` | true / false | 우회전할 때 횡단보도 보행자 신호가 녹색이었나 (차5-2, 기본 100:0) | 모델 또는 사용자 |
| `lane_change_in_intersection` | true / false | 직진 중 교차로 안에서 진로변경 (차5-1 B, +10) | 모델 |

차량 간 위치 관계(측면/맞은편)는 `heading_start`로 엔진이 계산한다. 회전 차량도 **회전하기 전 방향**이 필요하다.


### 3-6. 한쪽 지시표지 있는 교차로 (차7~차10)

| 필드 | 값 | 쓰이는 곳 | 출처 |
|---|---|---|---|
| `stop_sign` | true / false | 자기 진입로에 일시정지 표지(표지판 또는 노면표시)가 있는가. 정지선만 있으면 false. 있으면 차7~10, 양쪽 모두 없으면 신호 없는 교차로(차12~18) | 사용자 (2차: 표지 인식) |
| `stopped_before_entry` | true / false | 일시정지 위반 여부. 정지했으면 "일시정지 후 출발"(-10), 차7-1은 정지했으면 차12 대상 | 모델 |
| `one_way_violation` | true / false | 일방통행 역방향 진입 (차7-2) | 사용자 |
| `left_turn_prohibited_violation` | true / false | 좌회전 금지 위반 (차8, +20) | 사용자 |
| `left_turn_method_violation` | true / false | 좌회전 방법 위반: 중앙선 따라 서행하며 교차로 중심 안쪽으로 돌지 않음 (차10, +10) | 모델 |

차8-2/8-3, 9-1/9-2는 상대가 **오른쪽에서 왔는지 왼쪽에서 왔는지**로 기본 비율이 달라진다 (엔진이 `heading_start`로 판단).


### 3-7. 교차로 노면표시 위반 (차11)

같은 방향으로 나란히 가던 두 차가 교차로에서 부딪힌 사고로, **각자 있던 차로의 노면표시**와 실제 진행 방향이 다른지가 핵심이다.

| 필드 | 값 | 쓰이는 곳 | 출처 |
|---|---|---|---|
| `lane_marking` | `left_only` / `straight_left` / `straight_only` / `straight_right` / `right_only` | 교차로 진입 직전 그 차량이 있던 차로의 노면표시 화살표 | 모델(차선·노면표시 인식) 또는 사용자 |
| `no_lane_across` | true / false | 건너편에 이어지는 차로가 없어 진로를 바꿔야 했음 (A +10) | 모델 또는 사용자 |
| `could_foresee_other_turn` | true / false | 상대가 충분히 앞서 서서히 회전해 미리 알 수 있었음 (A +10) | 모델 |
| `yield_violation` | true / false | 오른쪽으로 피해 진로를 양보할 의무 위반 (차11-4 B +10) | 모델 |
| `started_from_parking` | true / false | 주정차 후 출발 중 사고 (차11-4 미적용) | 모델 |

두 차가 같은 방향이었는지는 `heading_start`로 엔진이 판단한다.


### 3-8. 신호등 없는 교차로 (차12~차18)

| 필드 | 값 | 쓰이는 곳 | 출처 |
|---|---|---|---|
| `road.road_width` | `equal` / `different` | 동일폭(차12-1, 13-1, 16-1 등) vs 대로·소로(차12-2, 13-3, 16-3 등) | 사용자 |
| `on_wider_road` | true / false | 대로·소로 교차로에서 그 차량이 대로 쪽인가. 한눈에 명확히 넓은 도로, 또는 중앙선·중앙분리대가 있거나 차로가 많은 우선도로 | 사용자 |
| `intersection_entry` | `{"frame", "t"}` | 차12의 기본 비율이 **동시 진입 / 선진입 / 후진입**으로 갈림 (1초 기준). 없으면 차12는 판정 보류 | 모델 |
| `slowed_before_entry` | true / false | 진입 전 서행·일시정지 (차12, -10). `stopped_before_entry`가 true면 자동으로 true | 모델 |
| `right_turn_method_violation` | true / false | 우회전 방법 위반 (차18-1, +10) | 모델 |

신호 없는 교차로 도표는 상대가 **오른쪽/왼쪽/맞은편/같은 방향** 중 어디서 왔는지와 도로 폭으로 기본 비율이 결정된다.


### 3-9. 교차로 부근 동시 회전 (차19~차21)

같은 방향으로 가던 두 차가 교차로에서 함께 회전하거나 한쪽이 회전하다 부딪힌 사고. **두 차의 앞뒤·좌우 위치**가 핵심이다.

| 필드 | 값 | 쓰이는 곳 | 출처 |
|---|---|---|---|
| `lead_order` | `leading` / `following` | 앞차·뒤차 구분 (차19-1, 20-2) | 모델 |
| `side_in_pair` | `left` / `right` | 나란히 가던 두 차 중 어느 쪽인가 (차20, 21) | 모델 |
| `road.lane_fits_two` | true / false | 한 차로가 2대가 나란히 지날 만큼 넓은가 (차19-1) | 사용자 |
| `cut_in` | true / false | 뒤에서 오른쪽 좁은 공간으로 끼어들었는가 (차20-2) | 모델 |
| `forced_cut_in` | true / false | 무리한 끼어들기·진로방해 (+10) | 모델 |
| `crossed_shoulder_or_sidewalk` | true / false | 갓길경계선·인도 침범 (차20-2 A, +10) | 모델 |
| `right_space_wide` | true / false | 앞차가 오른쪽에 넓은 공간을 남김 (차20-2 B, +10) | 모델 |


### 3-10. 마주보는 방향 사고 (차31~차33)

| 필드 | 값 | 쓰이는 곳 | 출처 |
|---|---|---|---|
| `road.center_line` | true / false | 중앙선 침범(차31) vs 중앙선 없는 도로 교행(차32) | 사용자 (2차: 차선 인식) |
| `road.center_line_rule_not_applied` | true / false | 중앙선이 있어도 좁은 도로 등으로 중앙선 침범을 적용하지 않는 경우 (차32) | 사용자 |
| `crossed_center_line` | true / false | 중앙선을 넘었는가 (차31-2~31-4) | 모델(차선 인식) |
| `wrong_way` | true / false | 중앙선을 넘어 역주행 (차31-1) | 모델 |
| `from_off_road` | true / false | 도로가 아닌 장소에서 나옴 (차31-2) | 모델 |
| `movement` | `reverse`, `u_turn` 값 추가 | 후진(차31-4), 유턴(차31, 33) | 모델 |
| `u_turn_type` | `always`(상시유턴구역) / `signal`(신호유턴) | 차33 기본 비율이 크게 갈림 (20:80 vs 100:0) | 사용자 |
| `ran_signal` | true / false | 상시유턴구역 사고에서 직진차의 신호위반 (차33-1 +80) | 모델 또는 사용자 |
| `overtook_in_no_passing_zone`, `crossed_double_solid_center` | true / false | 추월금지 장소 추월, 이중 실선 침범 | 모델 |
| `rear_inattention` | true / false | 후진 중 후방주시 태만 (차31-4 +20) | 사용자 |
| `going_uphill`, `crossed_virtual_center` | true / false | 비탈길에서 올라가는 차, 도로 가운데를 넘음 (차32) | 모델 |
| `stationary_at_collision`, `evasive_action` | true / false | 충돌 당시 정지, 회피 조치 (차32 각 -10) | 모델 |


### 3-11. 같은 방향 사고 (차41~차48)

추돌·진로변경·앞지르기처럼 같은 방향으로 가던 두 차의 사고. `lead_order`(앞차/뒤차)가 거의 모든 도표에 쓰인다.

| 필드 | 값 | 쓰이는 곳 | 출처 |
|---|---|---|---|
| `movement` | `lane_change` 값 추가 | 진로변경 (차43, 47) | 모델 |
| `stop_state` | `driving` / `accident_stop`(앞선 사고로 멈춤) / `parked`(주정차) | 추돌(차41) vs 재추돌(차42-1) vs 주정차 추돌(차42-2, 42-3) | 모델 + 사용자 |
| `position` | `lane` / `shoulder`(갓길) / `road_edge`(도로 가장자리) | 차42, 43-6 | 모델 |
| `road.road_type` | `general` / `highway`(자동차전용도로 포함) | 차42-2 vs 42-3, 고속도로 가산 | 사용자 |
| `merging` | true / false | 차로 감소·합류 (차43-1) | 모델 |
| `lane_change_dir` | `left` / `right` | 좌우 동시 진로변경 (차43-3) | 모델 |
| `from_congested_lane` | true / false | 정체 차로에서 대기 중 진로변경 (차43-4) | 모델 |
| `lane_change_first` | true / false | 같은 차로 뒤차가 먼저 진로변경 (차43-5) | 모델 |
| `to_shoulder` | true / false | 갓길로 진로변경 (차43-6) | 모델 |
| `through_safety_zone`, `in_safety_zone_at_collision` | true / false | 안전지대 통과, 충돌 시 안전지대 안이었나 (차43-7) | 모델 |
| `overtake_type` | `center_solid` / `right_side` / `no_passing_zone` / `center_in_congestion` / `close_range_center_dashed` / `white_solid` / `around_stopped` | 앞지르기 유형 (차45, 47-1) | 모델 + 사용자 |
| `u_turn_timing` | `sudden` / `simultaneous` | 뒤차 급유턴 vs 동시 유턴 (차46-1) | 모델 |
| `started_after_stop` | true / false | 정차 후 출발 (차47) | 모델 |
| `at_bus_stop`, `is_school_bus` | true / false | 버스정류장 출발 버스(차47-3), 어린이통학버스(-40) | 모델 + 사용자 |
| `dropped_cargo` | true / false | 앞차 적재물 낙하 (차48-1) | 모델 + 사용자 |
| `road.residential_area`, `road.low_visibility` | true / false | 주택가·상점가, 야간·악천후 시야 곤란 | 사용자 / 모델 |

수정요소용 필드(이유 없는 급정지, 제동등 고장, 비상등 점등, 안전표지 설치 등)는 `modifiers.json`의 각 항목 `when`에 적힌 이름을 그대로 쓴다.


### 3-12. 기타 유형 (차51~차55)

| 필드 | 값 | 쓰이는 곳 | 출처 |
|---|---|---|---|
| `road.location` | `parking_lot`, `roundabout` 값 추가 | 주차장(차51), 회전교차로(차54) | 사용자 |
| `in_parking_aisle`, `leaving_parking_space`, `entering_parking_space` | true / false | 주차장 통로 주행, 주차구획 출차·진입 (차51) | 모델 |
| `against_parking_arrow` | true / false | 주차장 화살표 반대 주행 (+10) | 모델 |
| `door_opening` | true / false | 정차 중 문 열림 (차52-1) | 모델 + 사용자 |
| `door_toward_traffic`, `sudden_door_open`, `door_at_transit_stop`, `door_open_foreseeable` | true / false | 문 열림 수정요소 | 사용자 |
| `road.night` | true / false | 야간 (+10) | 모델(밝기) |
| `crossing_on_crosswalk`, `ped_signal_at_crossing` | true / `red`·`green` | 이륜차 등이 횡단보도로 건넌 사고 (차53-1) | 모델 + 사용자 |
| `road.roundabout_lanes` | `single` / `multi` | 1차로형 vs 2차로 이상 회전교차로 | 사용자 |
| `roundabout_action` | `circulating` / `entering` / `exiting_lane_change` | 회전 중 / 진입 / 진출하려 진로변경 | 모델 |
| `roundabout_lane`, `entry_lane_from` | 1 / 2 | 회전 차로, 진입 전 차로 | 모델 |
| `big_entry` | true / false | 회전 1차로로 곧바로 크게 진입 (차54-2) | 모델 |
| `late_entry_no_yield` | true / false | 늦게 진입하며 양보 안 함 (차54-5) | 모델 |
| `is_emergency` | true / false | **긴급 용무 중인 긴급자동차**(경광등·사이렌). 이 값 하나로 차55 도표가 우선 선택됨 | 모델 + 사용자 |
| `driving_left_side` | true / false | 긴급자동차가 도로 중앙·왼쪽으로 통행 (차55-2, 55-3) | 모델 |
| `overtaking`, `sudden_lane_change` | true / false | 긴급 추월, 급차로변경 (차55-5, 55-6) | 모델 |


### 3-13. 자동차 대 이륜차 특수유형 (차61)

| 필드 | 값 | 쓰이는 곳 | 출처 |
|---|---|---|---|
| `between_congested_queue` | true / false | 이륜차가 정체 차량 오른쪽 좁은 공간으로 직진 (차61-1) | 모델 |
| `narrow_passing_space` | true / false | 그 공간이 대략 1.5m 미만 (+10) | 모델 + 사용자 |
| `on_sidewalk` | true / false | 이륜차가 보도(인도)로 주행 (차61-2) | 모델 |
| `to_off_road`, `stopped_before_sidewalk` | true / false | 도로가 아닌 장소로 우회전, 보도 횡단 전 일시정지 (차61-2) | 모델 |
| `passing_on_right` | true / false | 이륜차가 정차 차량 오른쪽으로 지나감 (차61-3) | 모델 |

### 3-14. 사고 유형 판단에 쓰는 값 (hmtm-0.1.0)

| 필드 | 값 | 설명 |
|---|---|---|
| `cls` | `vehicle`, `two_wheeler`, `bicycle`, `person`(A의 `pedestrian`도 받음), `farm_machine` | 충돌 당사자의 차종. 엔진이 이 값으로 사고 유형을 정한다. 보행자와 자전거도 `parties`에 넣고 `collision.between`에 포함해야 한다 |

- 사람이 충돌 당사자면 차대보행자, 자전거·농기계면 차대자전거로 판정한다.
- A의 탐지 클래스 이름 `pedestrian`은 변환기가 엔진의 `person`으로 바꾼다.
- `farm_machine`은 현재 탐지 클래스에 없다. 탐지 모델에 추가하기 전까지는 사용자 확인으로 넣는다.
- 보행자·자전거 사고용 필드는 3-15, 3-16절. 변환기는 `OPTIONAL_PARTY_FIELDS`(당사자)와 `SCENE_FIELDS`(장소, `road`에서 읽음)에 있는 이름만 엔진에 넘긴다.

**출처 구분** (3-15, 3-16): **영상** = 지금의 추적 결과(궤적·속도·영역)로 계산 가능, **모델** = 새 인식 모델이나 장면 정의(횡단보도·정지선 영역 등)가 있어야 함, **사용자** = 영상으로 알기 어려워 체크리스트로 받음. 여러 개면 앞이 우선, 뒤가 대안이다.

### 3-15. 차대보행자 (보1~보36, `rules_pedestrian.json`)

A = 자동차, B = 보행자. 원문은 보행자 과실만 적으므로 결과의 A = 100 − 보행자 과실.

`road`(장소)

| 필드 | 값 | 쓰이는 곳 | 출처 |
|---|---|---|---|
| `crosswalk_signal` | true / false | 횡단보도(부근)에 보행자 신호등이 있는지. 보1~보19(신호 있음) vs 보13·보20(없음) | 모델 + 사용자 |
| `location` | 기존 값 + `parking_lot` | 교차로·단일로·차도가 아닌 장소(보34) | 사용자 |
| `road_class` | 기존 값 + `expressway` | 고속도로·자동차전용도로 (보35, 보36) | 사용자 |
| `signal_present` | false | 보22는 신호 없는 교차로 (`signal.state = none`) | 사용자 |
| `night` | true / false | 야간 가산 | 영상 + 사용자 |
| `view_obstructed` | true / false | 시야장애 가산 (야간과 하나만) | 사용자 |
| `bad_weather` | true / false | 고속도로 악천후 (보35·보36, 야간과 하나만) | 모델 + 사용자 |
| `bright_place` | true / false | 밝은 곳 감산 | 사용자 |
| `arterial_road` | true / false | 간선도로 가산 | 사용자 |
| `ped_busy_area` | true / false | 주택·상점가·학교 부근 감산 | 사용자 |
| `protection_zone` | `child` / `elderly` / `disabled` / `none` | 보호구역 종류. 신호 없는 어린이보호구역(−30) | 사용자 (표지 인식은 모델) |
| `sidewalk_separated` | true / false | 보·차도 구분. 구분 없음 감산, 보도 있는데 차도 보행 가산 | 모델 + 사용자 |
| `center_line` | true / false | 보도 없고 중앙선 없음(−15) 등, 보27-1·보27-2·보28 구분 | 모델 + 사용자 |
| `crossing_prohibition` | `none` / `sign` / `barrier` | 횡단금지 표지(+10)·시설(+20), 하나만 | 모델 + 사용자 |
| `vehicle_access_zone` | true / false | 차량 출입 장소 가산 | 사용자 |
| `easy_walk_area`, `ped_warning_sign` | true / false | 고속도로에서 보행이 쉬운 곳, 보행자 주의 표지 (보35·보36 감산) | 사용자 |

`parties.<자동차>`

| 필드 | 값 | 쓰이는 곳 | 출처 |
|---|---|---|---|
| `movement` | 기존 값 + `reverse` | 후진 사고 (보32) | 영상 |
| `signal_at_entry` | `green` / `green_arrow` / `yellow` / `red` | 교차로 또는 횡단보도 정지선 진입 시점의 차량 신호 | 모델 + 사용자 |
| `right_turn_signal` | `green` / `red` / `none` | 우회전 신호기 (보17, 보18) | 모델 + 사용자 |
| `impact_after_intersection` | true / false | 교차로 통과 후(보1~보7) vs 통과 전(보8~보12) 충격 | 영상 (교차로 영역 필요) |
| `passed_crosswalk` | true / false | 횡단보도 통과 후(보14~보18) vs 통과 전(보19) | 모델 (횡단보도 영역 필요) |
| `passed_stopped_vehicles` | true / false | 정지 차량 옆을 지나 통과 (가산) | 영상 |
| `started_after_stop` | true / false | 정지 후 출발 (보행자 감산) | 영상 (블랙박스는 차량 기록) |
| `reverse_warning` | true / false | 후진 경고(경적 등)를 함 (보32) | 사용자 |
| `riding_on_crosswalk` | true / false | 이륜차가 횡단보도를 타고 건넘 (보33) | 모델 |
| `on_motorway` | true / false | 고속도로 본선 주행 | 사용자 |
| `speed_over_limit_kmh`, `avoidable_at_limit`, `user_factors` | 기존 값 | 이 장의 속도위반은 10km/h 이상부터 현저한 과실 | 기존과 같음 |

`parties.<보행자>`

| 필드 | 값 | 쓰이는 곳 | 출처 |
|---|---|---|---|
| `cls` | `person` (A는 `pedestrian`) | 사고 유형 판단 | 영상 |
| `ped_place` | `crosswalk` / `near_crosswalk` / `near_overpass` / `intersection` / `road` / `sidewalk` / `roadway` / `ped_only_road` / `ped_priority_road` | 도표 선택의 중심 값 | 모델 + 사용자 |
| `ped_activity` | `crossing` / `walking` / `lying_or_playing` | 횡단·보행·차도에서 놀기·누움 (보30) | 영상 (누움은 모델) |
| `ped_posture` | `sitting` / `lying` / `standing` | 보30 앉아 있음이 보였는지 | 모델 |
| `ped_signal_at_start`, `ped_signal_at_impact` | `green` / `flashing_green` / `red` | 횡단 시작·충격 때 보행자 신호 | 모델 + 사용자 |
| `crossing_place` (A 질문 답) | `on_crosswalk` / `near_crosswalk` / `carriageway` / `sidewalk` | 변환기가 `on_crosswalk`→`ped_place = crosswalk`, `near_crosswalk`→`near_crosswalk`로 바꿈 (hmtm-0.1.1). 나머지 둘은 뜻이 여럿이라 바꾸지 않음 (`docs/A_REQUESTS.md`) | 사용자 |
| `dist_from_crosswalk_m` | m | 횡단보도(육교·지하도)에서의 거리. 10~30m 가산 | 모델 + 사용자 |
| `crossing_road_width` | `narrower` / `equal` / `wider` | 신호 없는 교차로에서 건넌 도로 (보22) | 사용자 |
| `roadway_walk_position` | `edge_1m` / `beyond_1m` / `edge` / `center` | 차도 보행 위치 (보26, 보27-2, 보28) | 모델 |
| `sidewalk_closed` | true / false | 보도 공사로 차도 보행 (보25) | 사용자 |
| `diagonal_crossing` | true / false | 비스듬히 횡단 | 영상 |
| `inside_stop_line` | true / false | 정지선 안쪽 횡단 | 모델 (정지선 영역 필요) |
| `opposite_side_start` | true / false | 반대편에서 횡단 시작 | 영상 |
| `behind_before_reverse` | true / false | 후진 전부터 차 뒤에 있었음 (보32) | 영상 |
| `on_shoulder` | true / false | 고속도로 갓길 (보36) | 모델 + 사용자 |
| `expressway_walk_reason` | `none` / `justified` | 고속도로 보행 이유 (보35 vs 보36) | 사용자 |
| `vulnerable_type` | `child`(만 13세 미만) / `elderly`(만 65세 이상) / `disabled`(등록 장애인) / `none` | 어린이·노인·장애인 감산 | 사용자 |
| `in_own_protection_zone` | true / false | 보호구역 종류와 보행자가 맞음 (어린이보호구역의 어린이 등). 어린이 감산과 하나만 | 사용자 |
| `walk_manner` | `normal` / `stop` / `back` / `zigzag` | 멈춤·되돌아감·갈지자 보행 | 영상 |
| `ped_factors` | `group`, `sudden_entry`, `intentional_block`, `inline_skate` 중 해당 값 배열. 없으면 `[]`, 모르면 `null` | 집단 횡단, 갑자기 뛰어듦, 고의 막기, 인라인스케이트 등 | 영상(집단·뛰어듦) + 모델 + 사용자 |

### 3-16. 차대자전거 (거1~거43, `rules_bicycle.json`)

A = 자전거(농기계 포함), B = 자동차. 원문 A:B 그대로. 신호·일시정지·일방통행·대로·선진입·역주행처럼 차대차와 같은 이름의 필드는 차대차 절의 정의를 따른다.

`road`(장소)

| 필드 | 값 | 쓰이는 곳 | 출처 |
|---|---|---|---|
| `lanes_two_plus` | true / false | 2차로 이상 도로 (거41 가산) | 모델 + 사용자 |
| `dashed_bike_lane_border` | true / false | 차로와 자전거도로 사이 점선 (거43 가산) | 모델 + 사용자 |

`parties.<자전거>`

| 필드 | 값 | 쓰이는 곳 | 출처 |
|---|---|---|---|
| `cls` | `bicycle` / `farm_machine` | 사고 유형 판단 | 영상 (농기계는 사용자) |
| `movement` | 기존 값 + `lane_change` | 진로변경 (거32) | 영상 |
| `left_side_riding` | true / false | 도로 왼쪽 통행 가산 | 영상 |
| `bike_lane_nearby`, `in_bike_lane` | true / false | 자전거도로 부근인데 차도 통행(가산), 자전거도로 안(감산). 하나만 | 모델 + 사용자 |
| `diagonal_crossing` | true / false | 비스듬히 횡단 | 영상 |
| `path_blocked`, `obstacle_ahead` | true / false | 진로가 막힘, 앞에 장애물 (감산) | 모델 + 사용자 |
| `crossing_road` | true / false | 도로를 가로질러 횡단 (거41, 거33-2 구분) | 영상 |
| `on_bike_crossing` | true / false | 자전거횡단도로 횡단 (거42) | 모델 (횡단도 영역 필요) |
| `approached_right_edge` | true / false | 우회전 전 미리 우측 끝으로 다가섬 (거10) | 영상 |
| `bike_lane_type` | `dedicated_road` / `dedicated_lane` / `priority_road` / `none` | 자전거 전용도로·전용차로·우선도로 (거43) | 사용자 |
| `foresee_lane_change` | true / false | 자동차 진로변경을 예상할 수 있었음 (거43) | 사용자 |
| `vulnerable_type` | `child` / `elderly` / `disabled` / `none` | 어린이·노인·장애인 감산 | 사용자 |
| `user_factors` | `drunk_under_0.03`, `drunk_0.03_plus`, `overloaded`, `no_lights_night`, `one_hand`, `inattention`, `phone`, `zigzag`, `no_helmet`, `side_by_side`, `no_hand_signal`, `brake_failure`, `very_fast` | 자전거 운전자의 현저·중대한 과실 | 사용자 (`no_helmet`은 모델 가능) |

`parties.<자동차>`

| 필드 | 값 | 쓰이는 곳 | 출처 |
|---|---|---|---|
| `user_factors` | 기존 값 + `drowsy` | 졸음운전. 이 장에서는 중대한 과실(+20) | 사용자 |
| `speed_over_limit_kmh`, `avoidable_at_limit`, `turn_signal_used`, `sudden_lane_change`, `forbidden_lane_change`, `brake_light_failure`, `sudden_stop_without_reason`, `stopped_before_entry` | 기존 값 | 이 장의 속도위반은 10km/h 이상부터 현저한 과실 | 기존과 같음 |

## 4. `events` 추가

| type | 필드 | 설명 |
|---|---|---|
| `enter_zone` (zone = `intersection`) | `frame`, `t`, `track` | 교차로 영역 진입. scene.json에 교차로 영역이 있어야 함. `parties.<id>.intersection_entry`와 같은 값 |
| `signal_change` (2차) | `frame`, `t`, `from`, `to` | 신호 사고의 주의의무 범위 판단 |
| `line_crossing` (2차) | `frame`, `t`, `track`, `line` (`center` / `solid` 등) | 중앙선 침범, 진로변경 금지 위반 |

## 5. `unknowns`

```json
"unknowns": [
  {
    "field": "parties.22.movement",
    "question": "이 차량은 어느 방향으로 가려던 중이었나요?",
    "choices": ["직진", "좌회전", "우회전", "유턴", "모름"],
    "evidence_frame": 108
  }
]
```

## 6. 예시 (v0.3 최소 형태)

```json
{
  "schema_version": "0.3",
  "video": "data/videos/sample.mp4",
  "fps": 15.0,
  "road_type": "no_center_line",
  "road": {
    "location": {"value": "intersection", "source": "user"},
    "junction_type": {"value": "t", "source": "user"},
    "road_width": {"value": "equal", "source": "user"},
    "signal_present": {"value": false, "source": "user"},
    "speed_limit_kmh": {"value": 30, "source": "user"}
  },
  "collision": {"frame": 109, "t": 7.267, "a": "22", "b": "28", "zone": "road"},
  "parties": {
    "22": {
      "cls": "car",
      "movement": {"value": null, "source": "model", "evidence_frame": 108},
      "heading_start": [0.0198, 0.0004],
      "origin_zone": "side_entry_left",
      "enter_road": {"frame": 59, "t": 3.933},
      "intersection_entry": {"frame": 59, "t": 3.933},
      "intersection_entry_speed": 0.016,
      "user_factors": null
    },
    "28": {
      "cls": "two_wheeler",
      "movement": {"value": "straight", "source": "model", "evidence_frame": 100},
      "heading_start": [-0.0846, -0.1838],
      "intersection_entry": {"frame": 90, "t": 6.0},
      "intersection_entry_speed": 0.064,
      "damage_severity": null
    }
  },
  "events": [
    {"frame": 59, "t": 3.933, "type": "enter_zone", "track": "22", "zone": "intersection"},
    {"frame": 90, "t": 6.0, "type": "enter_zone", "track": "28", "zone": "intersection"}
  ],
  "unknowns": []
}
```

28번의 교차로 진입(90프레임, 6.0초)은 형식 설명용 예시값이다.

## 7. A 작업 우선순위

1. `intersection_entry` (교차로 영역 진입 시각): 명확한 선진입에 바로 쓰임
2. `intersection_entry_speed` (교차로 진입 순간 속도): 서행불이행의 정의에 맞춤
3. `unknowns` 출력: 진행 방향을 못 정한 차량 등
4. `movement`가 경계값(`min_disp` 0.02 등) 근처면 `unknowns`로 보내기
5. `wide_turn`, `off_right_side`: 차14-1 수정요소
6. (2차) 속도 보정 후 `speed_kmh`, 신호·선 넘음 이벤트
