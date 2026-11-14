# HMTM 앱 ↔ backend API 명세 (차량 데이터 사건) — v0.3

> **일부 내용은 구현과 다를 수 있음, 최신은 [README](../README.md).** 개발 중에 쓴 설계 문서로, "차량 기록은 참고 자료" 결정 이전 내용이 섞여 있다. 본문에 나오는 `*-notes.md`, `api-current.md`, devlog, CLAUDE.md는 내부 작업 기록이라 이 저장소에 넣지 않았다.

> 상태: **초안 v0.3** · 2026-11-09. 2절 주소 4개, 기록 검사·자동 답변 규칙(2.1, 4절), 어댑터·저장·탈퇴 때 삭제(8.2~8.6)가 모두 `backend/src/vehicle/`에 구현됨. 구현하며 정한 세부는 `docs/vehicle-rules-v0-notes.md`(A·B: 규칙, C: API 1부, E: API 2부).
> 현재 코드 기준 API는 `docs/api-current.md`(이하 "현황"). 질문 키·값은 현황 6절을 따른다.
> 기존 API(`/api/auth/*`, `/api/me*`, `/api/cases*`, `/api/posts*`)는 **그대로 두고**, 이 문서는 새 주소만 더한다.

**변경 이력**

| 판 | 날짜 | 내용 |
|---|---|---|
| v0 | 2026-11-08 | 첫 초안 |
| v0.3 | 2026-11-09 | API·어댑터 구현(notes C1~C14, E1~E11)에 맞춤. 없는·남의 사건 오류 코드를 `404 vehicle_case_not_found`로(GET·PUT·DELETE), JSON 아닌 본문은 `request_invalid`. `answers_shape`에 `answers` 키 없음·`null` 추가, `answer_invalid`의 "없는 질문 키"를 질문 키 모양 기준으로. `PUT`은 받은 답으로 통째로 바꿔 처음부터 다시 계산. `guess_source`에 `default` 추가, 어댑터 기본값(장소 교차로·사거리·신호 없음·도로 폭 비슷함) 명시, `road.signal_present`는 꼭 답할 사용자 질문(답 없으면 `false`, 출처 `default`). 서행 자동 답변은 신호 없음(답 없으면 기본값)일 때만. 자동 답변은 질문이 나올 때만 씀. `modifiers` 출처·`unverifiable_factors` 당사자·`provisional` 정의. 탈퇴 때 차량 사건 삭제(미들웨어, MTM 수정 없음) |
| v0.2 | 2026-11-09 | 규칙 v0 구현에 맞춰 세부 확정 (`docs/vehicle-rules-v0-notes.md`). 4.4 hard_brake 지시등 구간을 `[-10000, -1500]`으로 정하고 제외 구간에만 켜졌을 때의 근거 문장 추가(D13). 좌우 지시등이 둘 다 켜지면 진행 방향 추정 안 함(D14). 1초 미만 켜짐 `false`, 속도 기록이 없으면 지시등 `undetermined`, 후진 추정을 지시등 추정보다 먼저, brake `null` 처리, 빈 곳 판단 기준. 오류 코드 `request_invalid`, 같은 `t` 허용. `rules.run_rules`와 규칙 결과 모양(8.2) 추가 |
| v0.1 | 2026-11-08 | 앱 저장 방식 사실 수정 (72시간 루프 CSV, 100ms 고정 샘플링, brake 문자열 → bool 변환). 결정 D1~D12 확정(9절). `LEAD`를 속도 기준으로 확정. `DELETE /api/vehicle-cases/{id}` 추가. 구현 메모를 `src/vehicle/` 어댑터 구조로 변경 |

## 0. 범위와 용어

| 용어 | 뜻 |
|---|---|
| 차량 사건 (vehicle case) | 영상 없이 차량 기록(속도·기어·방향지시등·브레이크)만으로 만든 사건. 기존 영상 사건(`/api/cases`)과 다른 표·주소 |
| 자기 차 (`ego`) | 앱이 설치된 차. 차량 기록의 주인 |
| 상대 (`other`) | 부딪힌 상대 (차·이륜차·자전거·보행자). 차량 기록이 없으므로 모든 값을 사용자가 답함 |
| 사고 시각 `t_event` | 판정 규칙의 기준 시각. 앱의 급제동 북마크 시각 또는 사용자가 고른 시각 |
| 자동 답변 (auto answer) | 서버가 차량 기록으로 정한 답. `source: "vehicle"` |
| 남은 질문 | 자동 답변으로 못 정해서 사용자에게 묻는 질문 |

v0 목표는 **데모**다. 위치·지도 데이터가 없고, 영상도 연결하지 않는다.

**판정 엔진에서 당사자 이름**
- 당사자 id(판정 엔진의 track id)는 `ego`, `other` 두 개로 고정한다.
- 판정 결과의 `fault_by_track`도 `{"ego": 30, "other": 70}` 모양이 된다.

## 1. 전체 흐름

```
[차량 앱]                                         [backend]
0. 주행 중: 100ms마다 차량 상태 샘플링
   → 루프 기록 (1분 단위 CSV, 72시간 보관) ← 주 저장소
   → 메모리 버퍼 (최근 60초)
   급제동 감지 → 북마크(t_event) + 이벤트 파일
1. 사고 발생 → 사용자가 사고 구간 선택
   (급제동 북마크 목록에서 고르거나, 시각을 직접 지정)
   앱이 루프 CSV에서 그 구간을 잘라 samples로 변환
2. POST /api/vehicle-cases  ────────────────────▶  기록 검사 → 자동 답변 생성 (규칙 v0, 4절)
   {range, t_event, samples}                       → 판정용 사실(facts 0.3) 구성
                                                   → judge 판정 (남은 질문은 기본값·추정값으로 채워 임시 결과)
3. 응답: 자동 답변 + 남은 질문 (+ 임시 결과) ◀───  status = needs_answers / done
4. 남은 질문만 사용자에게 보여 줌
   (자동 답변은 "차량 기록으로 정함"으로 표시, 근거 문장 함께)
5. PUT /api/vehicle-cases/{id}/answers ─────────▶  답 검사 → 자동 답변 다시 계산
   {answers: 지금까지의 답 전부}                     (답에 따라 대상이 바뀜, 예: 진행 방향 → 지시등)
                                                   → judge 판정
6. 응답: 갱신된 남은 질문 + 결과 ◀─────────────── 질문이 남으면 4~6 반복
7. GET /api/vehicle-cases/{id} ─────────────────▶  저장된 결과 (과실비율, 적용 도표, 가감 요소)
8. (필요하면) DELETE /api/vehicle-cases/{id} ──▶  기록(samples)·답·결과 모두 삭제
```

**앱의 기록 저장 방식 (현재 `android/` 코드 기준)**

| 저장소 | 내용 | 이 API와의 관계 |
|---|---|---|
| **루프 기록** (주 저장소) | `VehicleCollectorService`가 **100ms마다** 최신 차량 상태를 그 시각으로 찍어(`VehicleHub.latest.copy(timestamp = now)`) `LoopRecorder`에 씀. 1분 단위 CSV(`files/loop/seg_<분 시작 ms>.csv`)에 쌓고 72시간이 지나면 지움. 헤더 `t,speedKmh,gear,turnSignal,brake` | **앱은 이 CSV에서 `range`에 해당하는 줄을 잘라 `samples`로 올린다.** 구간이 분 경계를 넘으면 여러 파일을 이어 붙임 |
| 메모리 버퍼 | 최근 60초 (`VehicleBuffer`) | 업로드에 쓰지 않음 |
| 이벤트 파일 | 급제동 감지 15초 뒤 버퍼 전체(앞 45초 + 뒤 15초)를 `files/events/event_<감지 ms>.json`으로 저장 | 파일 이름의 감지 시각이 `t_event`(`t_event_source: "hard_brake"`)의 출처. 이벤트 파일 자체는 올리지 않음 (루프 CSV가 같은 기록을 더 길게 가짐) |

**CSV → `samples` 변환 (앱이 업로드 전에 함)**

| CSV 열 | CSV에 저장된 모양 | `samples` 값 |
|---|---|---|
| `t` | epoch ms 숫자 | 정수 그대로 |
| `speedKmh` | `"%.2f"` 문자열, 값이 없으면 빈칸 | 숫자, 빈칸이면 `null` |
| `gear` | `VehicleGear` 정수 문자열 (예: `"8"`), 빈칸 가능 | `P`/`R`/`N`/`D` 문자열 (6.2 표), 빈칸·`0`이면 `null` |
| `turnSignal` | Pleos `TurnSignal`의 `toString()` 문자열, 빈칸 가능 | `LEFT`/`RIGHT`/`OFF`, 빈칸이면 `null` |
| `brake` | Pleos `Brake`의 `toString()` **문자열** (예: `"true"`), 빈칸 가능 | **bool로 변환** (`"true"` → `true`, `"false"` → `false`, 빈칸·그 밖 → `null`). 메모리 버퍼의 `exportJson`이 쓰는 `toBooleanStrictOrNull()`과 같은 규칙 |

**영상 사건과 다른 점**
- **작업자를 거치지 않음**: 차량 사건에는 YOLO 탐지가 없어서, 판정을 **요청 안에서 바로** 끝낸다(1초 안쪽 예상). 그래서 `analyzing` 상태와 폴링이 없다.
- **답 검사도 바로**: 답 값 검사 오류도 요청에 대한 응답으로 바로 `422`를 돌려준다. 기존 `PUT /api/cases/{id}/answers`가 `202`를 먼저 돌려준 뒤 `error` 칸으로 알리는 것과 다르다.
- **같은 방식**: 답은 기존과 같이 **매번 전부** 보낸다. 서버는 이전 답을 합치지 않고 받은 답으로 처음부터 다시 계산한다.

## 2. 신규 엔드포인트

| 메서드 | 경로 | 용도 | 성공 응답 |
|---|---|---|---|
| POST | `/api/vehicle-cases` | 차량 기록으로 사건 생성 + 자동 답변 + 임시 판정 | `201` 차량 사건 |
| PUT | `/api/vehicle-cases/{id}/answers` | 사용자 답 → 자동 답변 다시 계산 → 판정 | `200` 차량 사건 |
| GET | `/api/vehicle-cases/{id}` | 사건과 결과 | `200` 차량 사건 |
| DELETE | `/api/vehicle-cases/{id}` | 사건 삭제 (samples 포함 전부) | `204` |

**공통 규칙**
- **인증**: 5절.
- **남의 사건과 없는 사건**: 둘을 구분하지 않고 똑같이 `404 vehicle_case_not_found`로 답한다 (남의 사건이 있는지 알리지 않음). 영상 사건의 `case_not_found`와 구분하려고 이름을 따로 둔다. GET·PUT·DELETE 모두 같다.
- **본문이 JSON이 아니면**: POST·PUT 모두 `422 request_invalid`. FastAPI 기본 오류 모양 대신 아래 오류 모양으로 나간다.
- **오류 모양**: 기존과 같은 `{"error": "<코드>", "message": "<사용자에게 보여 줄 한국어>"}`.
- **시각**: 6절. 이 문서의 모든 시각은 **epoch 밀리초 정수**다.
- **키 이름**: 기록(samples) 항목은 앱의 루프 CSV 헤더와 같은 camelCase(`t`, `speedKmh`, `gear`, `turnSignal`, `brake`)를 쓴다. 그 밖의 키는 기존 API처럼 snake_case를 쓴다.
- **v0에 없는 기능 (기존 영상 사건에는 있음)**: 목록, 보관함, 자동 삭제(보관 기간), 투표는 없다 (7절 미정). 삭제(2.4)와 탈퇴 때 삭제(5절)는 v0에 있다.

### 2.1 `POST /api/vehicle-cases`

**요청** (`application/json`)

```json
{
  "range": {"from": 1762581600000, "to": 1762581660000},
  "t_event": 1762581652300,
  "t_event_source": "hard_brake",
  "samples": [
    {"t": 1762581600012, "speedKmh": 42.5, "gear": "D", "turnSignal": "OFF", "brake": false},
    {"t": 1762581600112, "speedKmh": 42.3, "gear": "D", "turnSignal": "OFF", "brake": false},
    {"t": 1762581600212, "speedKmh": 42.1, "gear": "D", "turnSignal": "RIGHT", "brake": false}
  ],
  "vehicle": {"cls": "car"},
  "location": null,
  "client": {"app_version": "0.1.0"}
}
```

| 키 | 형식 | 필수 | 뜻·규칙 |
|---|---|---|---|
| `range.from`, `range.to` | int (ms) | 예 | 올린 기록 구간. `from < to`, 길이 120초 이하 (루프 기록은 72시간이지만 한 사건에 올리는 구간은 120초까지) |
| `t_event` | int (ms) | 예 | 사고 시각. `range` 안이어야 하고, 앞쪽 기록이 3초 이상 있어야 함 (`from ≤ t_event - 3000`) |
| `t_event_source` | string | 예 | `hard_brake`(급제동 북마크 시각 그대로) / `manual`(사용자가 고르거나 고친 시각). 규칙이 기준 시각을 다르게 해석함 (4.1) |
| `samples` | array | 예 | 1개 이상, 20,000개 이하, `t` 오름차순. 모두 `range` 안. 100ms 샘플링이면 120초에 약 1,200개 |
| `samples[].t` | int (ms) | 예 | 기록 시각 (앱 시계. 샘플링한 순간의 `System.currentTimeMillis()`) |
| `samples[].speedKmh` | number \| null | 예 | 차속 km/h (0 이상) |
| `samples[].gear` | string \| null | 예 | `P` / `R` / `N` / `D`. 모르면 `null` (6.2) |
| `samples[].turnSignal` | string \| null | 예 | `LEFT` / `RIGHT` / `OFF`. 모르면 `null` |
| `samples[].brake` | bool \| null | 예 | 브레이크 페달을 밟았는지. CSV에는 문자열로 저장되므로 **앱이 업로드 전에 bool로 변환**함 (1절 변환표). 문자열(`"true"`)을 보내면 `sample_invalid` |
| `vehicle.cls` | string | 아니오 | 자기 차 종류 (`car` 기본, `truck`, `bus`, `two_wheeler`). 이 값이 `parties.ego.cls`가 됨: `answers`에 `{"value", "source": "vehicle"}`로 들어가고 판정에도 출처 `vehicle`로 넘어감. 규칙 이름·근거가 없어서 `auto_answers`(3절)에는 넣지 않음. 질문하지 않음 |
| `location` | null | 아니오 | **예약 칸.** v0는 `null`만 받음. 위치·교차로 데이터를 넣을 자리 (7절) |
| `client.app_version` | string | 아니오 | 기록용 |

**기록 해석**
- 앱 서비스는 **100ms마다 일정하게** 샘플링한다 (`VehicleCollectorService.SAMPLE_MS`). 각 줄은 그 순간의 최신 차량 상태다. 차량 값이 바뀌지 않았으면 같은 값이 반복된다.
- 서버는 각 값을 **다음 기록이 올 때까지 유지된 것**으로 본다. 즉 시각 `t`의 상태는 `t` 이전(`t` 포함)의 마지막 기록이다.
- `samples`의 `t`는 같은 값이 이어져도 된다 (샘플링이 밀린 경우). 같은 시각이면 뒤 기록이 이긴다.
- 이 규칙 덕분에 간격이 일정하지 않은 기록(앱이 바뀌거나 샘플링이 밀린 경우)도 같은 방식으로 읽힌다.
- 두 기록 사이가 **2초보다 벌어지면**(간격 > 2000ms, 정확히 2초는 아님) 그 구간은 "기록 없음"으로 본다. 앱이 꺼졌거나 서비스가 멈춘 경우다. 그 구간에 조금이라도 걸치는 규칙은 판정하지 않는다(`undetermined`).
- 첫 기록 앞과 `range.to` 뒤도 기록 없음이다. 이쪽은 규칙 구간 안에서 2초를 넘을 때만 `undetermined`로 본다.
- 서비스는 1초(10줄)마다 디스크에 반영하므로, 갑자기 전원이 꺼지면 마지막 1초 정도가 빠질 수 있다.

**응답 `201`**: 차량 사건 (2.5).

**오류**

| 코드 | HTTP | 언제 |
|---|---|---|
| `request_invalid` | 422 | 요청 모양 오류: 본문이 JSON이 아님, 본문이 객체가 아님, `samples`가 배열이 아님, `t_event_source`가 `hard_brake`/`manual`이 아님, `vehicle`·`client`가 객체가 아님, `vehicle.cls`가 보기에 없음 |
| `range_invalid` | 422 | `from ≥ to`, 120초 초과, 정수가 아님 |
| `t_event_out_of_range` | 422 | `t_event`가 구간 밖이거나 앞쪽 기록이 3초 미만 |
| `samples_empty` / `samples_too_many` | 422 | 0개 / 20,000개 초과 |
| `samples_unsorted` | 422 | `t`가 앞 기록보다 작음 (같은 값은 허용) |
| `sample_invalid` | 422 | 값 형식 오류 (예: `gear: "X"`, `speedKmh: -3`), 키 빠짐, `t`가 `range` 밖. `message`에 몇 번째 항목인지 (`samples[12]: …`) |
| `location_unsupported` | 422 | `location`이 `null`이 아님 (v0) |

### 2.2 `PUT /api/vehicle-cases/{id}/answers`

**요청**

```json
{"answers": {"parties.ego.movement": "right_turn",
             "parties.other.movement": "straight",
             "parties.other.entry_from": "left",
             "road.signal_present": false}}
```

- **지금까지의 답 전부**를 보낸다. 키는 질문의 `field`, 값은 `options` 중 하나다 (`multi`는 배열).
- 자동 답변이 정한 키를 사용자가 보내면 **사용자 답이 우선**한다. 그 질문은 `answer_conflicts`에 남는다 (2.5). 앱은 결과 화면에서 "차량 기록과 다르게 입력함"으로 보여 준다.
- 서버는 받은 답으로 자동 답변을 **다시 계산**한다. 예: 진행 방향을 `right_turn`으로 답하면 그때 `turn_signal_used`의 자동 답변이 생긴다.
- **통째로 바꿈**: 저장해 둔 요청 원본(samples 등)으로 규칙·질문·판정을 **처음부터 다시** 돌려 사건을 덮어쓴다. 이전 답과 합치지 않고 받은 `answers`로 바꾼다. 빈 객체 `{}`를 보내면 POST 직후 상태로 돌아간다. `id`·`created_at`은 그대로, `updated_at`만 바뀐다.
- **사라진 질문의 답**: 앞 답을 바꿔 지금은 없는 질문(예: 진입 순서를 `same_time`으로 바꾼 뒤의 `intersection_entry_clear`, 장소를 바꾼 뒤의 `entry_from`)의 답이 섞여 와도 오류가 아니다. 키 모양(아래)이 맞으면 받아서 판정 가정에 넘긴다 (영상 사건과 같음).

**응답 `200`**: 차량 사건 (2.5).

**오류**

| 코드 | HTTP | 언제 |
|---|---|---|
| `request_invalid` | 422 | 본문이 JSON이 아님 |
| `answers_shape` | 422 | 본문이 객체가 아님, `answers` 키가 없음, `answers`가 `null`이거나 객체가 아님 |
| `answer_invalid` | 422 | 지금 질문에 있는 키의 값이 보기에 없음, 또는 **질문 키 모양이 아닌 키**. 질문 키 모양: `parties.(ego\|other).*`, `road.*`, `scene.place`·`scene.junction_type`, `situation.*`, `intersection_entry_*`. 모양이 맞지만 지금 질문에 없는 키는 오류가 아님(위). `message`에 어느 키인지 (기존 문구 형식) |
| `vehicle_case_not_found` | 404 | 없는 사건, 남의 사건 (구분하지 않음) |

### 2.3 `GET /api/vehicle-cases/{id}`

**응답 `200`**: 차량 사건 (2.5). 마지막 `POST`·`PUT`의 결과와 같다.

**오류**

| 코드 | HTTP | 언제 |
|---|---|---|
| `vehicle_case_not_found` | 404 | 없는 사건, 남의 사건 (구분하지 않음) |

### 2.4 `DELETE /api/vehicle-cases/{id}`

- **응답**: `204` (본문 없음).
- **지우는 것**: 그 사건의 모든 것. 요청 원본(`samples`, `range`, `t_event`, `vehicle`, `client`), 사용자 답, 자동 답변, 판정 결과, 판정용 사실(facts).
- **되돌릴 수 없다.** 기존 영상 사건과 달리 휴지통·보관 기간이 없다.
- **그 밖의 사본도 남기지 않음**: 서버 로그와 임시 파일에도 samples를 남기지 않는다. 기존 서버의 "로그에 영상 이름·답을 남기지 않는다" 원칙과 같다. 판정할 때 쓰는 임시 파일에는 판정용 사실(facts) 껍데기만 들어가고(samples 없음) 판정이 끝나면 바로 지운다.
- 사건이 samples까지 행 하나에 들어 있어서 행 하나를 지우면 끝난다 (8.6).
- 앱의 루프 CSV는 앱 쪽 기록이라 이 요청과 관계없다. 72시간 뒤 앱이 지운다.

**오류**

| 코드 | HTTP | 언제 |
|---|---|---|
| `vehicle_case_not_found` | 404 | 없는 사건, 남의 사건 (구분하지 않음) |

### 2.5 차량 사건 객체

```json
{
  "id": "3f2a…",
  "status": "needs_answers",
  "created_at": 1762581700123,
  "updated_at": 1762581745001,
  "event": {"t_event": 1762581652300, "t_event_source": "hard_brake",
            "range": {"from": 1762581600000, "to": 1762581660000}},
  "data_quality": {"samples": 412, "gaps": [], "fields_missing": [], "clock_warnings": []},
  "parties": {"ego": {"label": "내 차", "cls": "car"}, "other": {"label": "상대", "cls": null}},
  "auto_answers": [ … 3절 … ],
  "answers": {"parties.ego.movement": {"value": "right_turn", "source": "user"},
              "parties.ego.turn_signal_used": {"value": true, "source": "vehicle"}},
  "answer_conflicts": [],
  "questions": [ … 2.6 … ],
  "result": { … 2.7 … } ,
  "judge_version": "0.13.1"
}
```

| 키 | 뜻 |
|---|---|
| `status` | `needs_answers` (꼭 답해야 하는 질문이 남음) / `done` (선택 질문만 남거나 없음). 값의 뜻은 영상 사건의 `app.json`과 같음. 기본값이 있어도 꼭 답할 질문(`optional: false`)이면 답하기 전까지 `needs_answers` (예: `road.signal_present`) |
| `data_quality.gaps` | 2초 넘게 기록이 빈 구간 `[{"from", "to"}]` |
| `data_quality.fields_missing` | 사고 시각 주변(`t_event` 앞 10초)에서 모두 `null`인 값 이름 (예: `["turnSignal"]`) |
| `data_quality.clock_warnings` | 기록 시각이 서버가 받은 시각과 하루 넘게 다르면 경고 (6.1, 2026-11-11). 없으면 `[]` |
| `auto_answers` | 서버가 차량 기록으로 **정한** 답 (3절). 판정할 수 없었던 규칙은 여기 없이 `questions`의 추정값으로 감 |
| `answers` | 판정에 실제로 쓴 답 전체. 값마다 `source`: `vehicle`(자동 답변, `parties.ego.cls`) / `user`(사용자 답) / `default`(답이 없어 기본값·추정값으로 채움). `default`에는 어댑터 기본값(장소 `intersection`, 교차로 모양 `cross`, 신호 없음 `false`, 도로 폭 비슷함 `equal`, 2.6)과 남은 질문의 추정값이 모두 들어간다. 추정값이 차량 기록에서 왔어도(`guess_source: "vehicle"`) 사용자가 답하지 않았으면 `default`다. 블랙박스 사건(`/api/bb-cases`)의 `default` 값에는 `basis`가 붙는다: `guess`(영상·차량 기록 추정값, 앱 "추정" 배지) / `default`(기본값, 앱 "가정" 배지) |
| `answer_conflicts` | 사용자 답이 자동 답변과 다른 질문 `[{"field", "vehicle_value", "user_value", "evidence"}]` |
| `parties` | `ego`는 `{"label": "내 차", "cls": vehicle.cls}`, `other`는 `{"label": "상대", "cls": parties.other.cls 답 또는 null}` |
| `questions` | 남은 질문 (2.6) |
| `result` | 판정 결과 (2.7). 남은 질문이 있어도 기본값·추정값으로 채운 **임시 결과**가 들어감 (`provisional: true`) |

### 2.6 남은 질문 (`questions[]`)

기존 질문 모양(`app_io.md` 3.5)과 같다. 다만 영상이 없어서 `evidence_frame`·`image`가 빠지고, 차량 기록 추정을 나타내는 두 키가 더해진다.

```json
{"field": "parties.ego.movement",
 "question": "내 차는 어느 방향으로 가고 있었나요?",
 "answer_type": "choice",
 "options": ["straight", "left_turn", "right_turn", "u_turn", "lane_change", "reverse", "unknown"],
 "choices": ["직진", "좌회전", "우회전", "유턴", "진로 변경 (차로 바꾸기)", "후진", "모름"],
 "model_guess": "right_turn",
 "guess_source": "vehicle",
 "guess_evidence": "사고 4.1초 전부터 오른쪽 지시등이 켜져 있었어요",
 "default": false, "optional": false, "group": null, "depends_on": null}
```

| 키 | 뜻 |
|---|---|
| `model_guess` | 미리 골라 둘 값. 차량 기록 추정이면 `guess_source: "vehicle"`, 어댑터 기본값이면 `guess_source: "default"` |
| `guess_source` | (새 키) `model_guess`가 어디서 왔는지. `vehicle`(차량 기록 추정) / `default`(어댑터 기본값, 아래 표의 "기본값") / `null`(추정값 없음). 앱이 "차량 기록으로 추정함"과 "기본값"을 구분해 보여 줄 수 있게 `default`를 따로 둔다 |
| `guess_evidence` | (새 키) 추정 근거 문장. 주로 `guess_source`가 `vehicle`일 때. 추정값이 없어도 못 정한 이유나 사실 근거를 담을 수 있음 (3절) |
| `default` | 기존 키. `true`면 기본값으로 정해 둔 질문이라 답하지 않아도 됨 (`status`에 영향 없음). `road.signal_present`처럼 `guess_source: "default"`여도 `default: false`면 꼭 답할 질문 |
| 나머지 | 기존과 같음 (`depends_on`, `optional`, `group`, `option_groups`, `all_options` 등) |

**v0 차량 사건의 질문 목록**
- 현황 6.3의 질문 중에서 영상이 없어도 뜻이 통하는 것만 쓴다.
- 영상 전용 질문은 내지 않는다: 부딪힌 쌍 고르기, 직접 표시, 진입 장면 고르기, 신호등 연결, 바닥 화살표.
- 화면 기준 보기는 **자기 차 기준 보기**로 바꾼다 (아래 ★).
- 상황 질문(`situation.questions`)의 문구에 나오는 "`ego`번 차"/"`other`번 차"는 "내 차"/"상대 차"로 바꾼다. 충돌 위치는 교차로 안으로 고정해 "충돌이 교차로 안이었나" 질문은 내지 않는다.
- **자동 답변은 그 질문이 나올 때만** 쓴다 (질문 조건과 `depends_on`을 따짐). 지시등은 회전·진로 변경일 때, 서행은 신호 없는 교차로일 때만 질문이 나오므로, 질문이 안 나오면 자동 답변도 `auto_answers`·판정에 넣지 않는다. 이때 답이 없는 `road.signal_present`는 기본값(`false`)으로 보고 따진다 (4.5).

| `field` | 질문 | 보기 | 비고 |
|---|---|---|---|
| ★ `scene.place` | 사고 장소 | `intersection` `roundabout` `parking_lot` `straight` | **새 키.** 영상 사건은 모서리 단계(`PUT /scene`의 `place`)에서 받던 값. **기본값 `intersection`** (`default: true`, `guess_source: "default"`) |
| ★ `scene.junction_type` | 교차로 모양 | `cross`(사거리) `t`(삼거리) | **새 키.** 교차로일 때만. **기본값 `cross`** (`default: true`, `guess_source: "default"`) |
| `parties.ego.movement` | 내 차 진행 방향 | 현황과 같음 | 자동 답변 또는 추정 (4.3) |
| `parties.other.cls` | 상대 종류 | `car` `truck` `bus` `two_wheeler` `bicycle` `farm_machine` `pedestrian` | |
| `parties.other.movement` | 상대 진행 방향 | 현황과 같음 | |
| ★ `parties.other.entry_from` | 상대는 어느 쪽에서 왔나 | `left` `right` `opposite` `same` (내 차 기준 왼쪽 길 / 오른쪽 길 / 맞은편 / 같은 방향) | **보기 변경.** 아래 방위 변환 |
| `road.signal_present` | 신호등 유무 | `true` `false` | 교차로일 때. **꼭 답할 사용자 질문** (`default: false`, `model_guess: false`, `guess_source: "default"`). 영상이 없어 신호등을 볼 수 없어서 묻는다. 답하기 전에는 `status: needs_answers`이고, 판정에는 `false`(1차 범위 비신호 교차로)를 넣고 `answers`에 `source: "default"`, `auto_filled`에 넣음. 위치 데이터가 생기면 자동 답변 (7절) |
| `parties.ego.signal_at_entry`, `parties.other.signal_at_entry` | 진입 때 신호 색 | 현황과 같음 | 신호 있음일 때 |
| ★ `road.wider_road` | 어느 도로가 넓은가 | `equal` `mine` `theirs` (비슷함 / 내 차 도로 / 상대 도로) | **보기 변경.** 상대가 `left`·`right`일 때만 (`depends_on: {"parties.other.entry_from": ["left", "right"]}`). **기본값 `equal`** (`default: true`, `guess_source: "default"`). 질문이 안 나왔거나 답이 없으면 판정에 `equal`을 넣고 `answers`에 `source: "default"`, `auto_filled`에 넣음 (8.4) |
| `road.center_line` | 중앙선 유무 | `true` `false` | |
| `intersection_entry_order` | 누가 먼저 들어갔나 | `ego` `other` `same_time` | 교차로 |
| `intersection_entry_clear` | 확실히 먼저였나 | `true` `false` | 위 답이 `ego`/`other`일 때 |
| `parties.ego.turn_signal_used` | 내 차 지시등 | `true` `false` | **자동 답변 대상** (4.4). 판정 못 하면 질문 |
| `parties.other.turn_signal_used` | 상대 지시등 | `true` `false` | 사용자 |
| `parties.ego.slowed_before_entry` | 내 차 서행 | `true` `false` | **자동 답변 대상** (4.5) |
| `parties.other.slowed_before_entry` | 상대 서행 | `true` `false` | 사용자 |
| `situation.special` | 특수 상황 | 현황 6.3 | 보기 키의 당사자 부분은 `ego`/`other` (예: `reverse:ego`). 후진 확정이면 `model_guess`에 `reverse:ego`가 더해지고 `guess_source: "vehicle"` (4.2) |
| `parties.<ego\|other>.driver_factors` | 운전자 요인 | 현황 6.3 | 선택 질문 |
| 그 밖의 상황 질문 | 일시정지 표지, 유턴 종류, 서 있던 이유, 회전교차로·주차장 등 | 현황 6.3과 같음 | 앞 답에 따라 생김 (`situation.questions`와 같은 조건) |

**방위 변환 (★ 보기)**
- 판정 엔진은 진입 방위(`entry_from`: 동서남북)로 두 차의 좌우 관계를 본다. 영상 사건의 보기는 화면 기준이었다.
- 차량 사건은 **자기 차가 남쪽에서 북쪽으로 들어왔다고 고정**한다 (`parties.ego.entry_from = south`). 상대 답은 다음과 같이 바꿔서 판정 엔진에 넘긴다.

| 상대 답 | 엔진 값 |
|---|---|
| `left` | `west` |
| `right` | `east` |
| `opposite` | `north` |
| `same` | `south` |

- `road.wider_road`도 같은 고정으로 바꾼다: `mine` → `north_south`, `theirs` → `east_west`, `equal` → `equal`.

### 2.7 판정 결과 (`result`)

```json
{
  "status": "ok",
  "provisional": false,
  "rule_id": "차12-1(다)",
  "title": "직진 대 직진 (동시진입)",
  "fault_by_party": {"ego": 30, "other": 70},
  "base_fault_by_party": {"ego": 40, "other": 60},
  "modifiers": [
    {"label": "B 명확한 선진입", "party": "other", "delta": -10, "source": "user",
     "facts": ["entry_lead_sec"], "needs_proof": true},
    {"label": "진로변경 신호 불이행", "party": "ego", "delta": 10, "source": "vehicle",
     "facts": ["turn_signal_used"], "needs_proof": false}
  ],
  "unverifiable_factors": [],
  "auto_filled": ["road.center_line"],
  "notice": null
}
```

| 키 | 뜻 |
|---|---|
| `status` | `ok` (도표를 찾음) / `no_rule` (맞는 도표 없음, 비율 `null`) |
| `provisional` | 꼭 답해야 하는 질문이 남아 기본값·추정값으로 채운 결과인지. 사건 `status`가 `needs_answers`이면 `true` |
| `rule_id`, `title` | 적용 도표 번호와 이름 (판정 엔진 결과 그대로) |
| `fault_by_party` | 당사자별 최종 과실 %. 판정 엔진의 `fault_by_track`(id가 `ego`/`other`) 그대로 |
| `base_fault_by_party` | 가감 전 기본 과실 % (판정 엔진 계산 과정의 `base` 단계) |
| `modifiers` | 적용된 가감 요소. `party`는 `ego`/`other`, `facts`는 판정 엔진이 그 요소에 쓴 사실 이름(엔진 `observed`의 키), `source`는 아래 출처 규칙 |
| `unverifiable_factors` | 기록·답으로 알 수 없어 반영하지 않은 요소. 모양은 기존과 같고, `party`만 엔진 역할(`A`/`B`) 대신 `ego`/`other` (`modifiers`와 맞춤) |
| `auto_filled` | 답이 없어 기본값·추정값으로 채운 질문 키. 어댑터 기본값(`scene.place`, `scene.junction_type`, `road.signal_present`, `road.wider_road`)도 답이 없으면 들어감 |
| `notice` | 보행자·자전거 장 미지원 같은 안내 (기존 `verdict.notice`) |

**`modifiers[].source` 정하는 법**
- 근거 사실(`facts`)마다 그 요소 당사자의 질문 키 `parties.<당사자>.<사실 이름>`을 찾아 `answers`의 `source`를 본다.
- 하나라도 `user`면 `user`.
- 사용자 답이 없고 `vehicle`이 있으면 `vehicle`.
- 둘 다 아니면 `default`.
- 사실 이름이 질문 키와 다른 것(예: `entry_lead_sec` ← `intersection_entry_order`)은 찾지 못해 `default`로 나온다. 이름 대응표는 미정 (7절).

**판정에 넘기는 규칙 사실**: 규칙 결과의 `facts`(8.2) 중 `stopped_before_entry`, `stationary_at_collision`만 출처 `vehicle`로 판정에 넘긴다. `intersection_entry_speed_kmh`는 저장만 한다 (판정 엔진의 진입 속도는 영상 기준 값이라 단위가 다름).

**`needs_proof`**: 판정 엔진 값 그대로다. 엔진은 출처가 `user`인 사실로 적용된 요소에만 "입증 필요"를 붙인다. 그래서 차량 기록(`vehicle`) 값은 입증된 것으로 취급된다 (D6 확정).

## 3. 자동 답변 형식

```json
{
  "field": "parties.ego.turn_signal_used",
  "value": true,
  "source": "vehicle",
  "rule": "turn_signal_v0",
  "evidence": {
    "text": "사고 3.2초 전 오른쪽 지시등 켜짐 (사고 때까지 켜져 있음)",
    "window": {"from": 1762581642300, "to": 1762581652300},
    "points": [{"t": 1762581649100, "key": "turnSignal", "value": "RIGHT"}]
  }
}
```

| 키 | 뜻 |
|---|---|
| `field` | 질문 키 (2.6 목록과 같은 이름). 답이 정해졌으므로 이 질문은 `questions`에서 빠짐 |
| `value` | 답 값 (질문의 `options` 중 하나) |
| `source` | 자동 답변은 늘 `vehicle`. 사용자 답은 `answers`에서 `user`로 구분 |
| `rule` | 판정한 규칙 이름과 버전 (4절). 규칙을 고치면 버전을 올림 |
| `evidence.text` | 사용자에게 보여 줄 한국어 근거 한 문장. 시각은 "사고 N.N초 전"처럼 `t_event` 기준으로 씀 |
| `evidence.window` | 규칙이 본 구간 (ms) |
| `evidence.points` | 근거가 된 기록 시점 (앱이 그래프에 표시할 때) |

**정하지 못한 규칙은 이렇게 처리함**
- 결과가 `undetermined`인 규칙은 `auto_answers`에 넣지 않는다. 그 질문을 `questions`에 남긴다.
- 추정할 수 있는 값이 있으면 `model_guess`와 `guess_source: "vehicle"`, `guess_evidence`를 붙인다.
- 기록이 비어서 판정을 못 했다면 `guess_evidence`에 그 이유를 적는다 (예: "사고 전 지시등 기록이 없어요"). 이때 `model_guess`가 없으므로 `guess_source`는 `null`이다. 즉 `guess_source: "vehicle"`은 **추정값이 있을 때만** 붙고, `guess_evidence`는 추정값이 없어도 이유나 사실 근거를 담을 수 있다.
- `guess_source`는 셋 중 하나다: `vehicle`(차량 기록 추정, 이 절의 규칙) / `default`(어댑터 기본값, 2.6) / `null`(추정값 없음).

## 4. 자동 답변 규칙 v0

모든 숫자는 **임시값**이다. 실차 기록으로 조정해야 한다. 규칙 이름 끝의 `_v0`은 규칙 버전이다.

### 4.1 공통

**기호**
- `T` = 기준 시각.
- `state(key, t)` = `t` 이전(`t` 포함) 마지막 기록의 값.
- `구간 [a, b]` = `T+a ~ T+b` (ms, 보통 음수).

**`T` 정하는 법 (`t_event_source`에 따라)**

| `t_event_source` | `T` | 이유 |
|---|---|---|
| `hard_brake` | `t_event` 그대로. 다만 **`[-1500, 0]`은 "충돌 직전 제동 구간"으로 보고 서행·지시등 판단에서 뺀다** | 앱 급제동 감지(`HardBrakeDetector`)는 "최근 1초 감속 ≥ 15km/h/s, 출발 속도 ≥ 20km/h"일 때 울린다. 그래서 `t_event`는 급제동이 **시작된 뒤 약 0.5~1초**이고 충돌 직전·직후일 수 있다. 피하려고 밟은 브레이크를 "진입 전 서행"으로 세지 않으려고 뺀다 |
| `manual` | `t_event` 그대로 (사용자가 "부딪힌 순간"으로 고른 시각이라고 봄) | 앱 화면에서 "부딪힌 순간을 골라 주세요"로 받는다 (D2 확정) |

**기록 품질**
- 규칙이 보는 구간에 2초 넘는 빈 곳(2.1 기록 해석)이 걸치면 `undetermined`. 근거 "사고 전 기록이 2초 넘게 끊긴 곳이 있어요".
- 필요한 값이 모두 `null`이어도 `undetermined`.
- `null`은 "모름"이다. "안 켰음"·"브레이크 안 밟음"으로 세지 않는다 (4.3 조건, 4.5 `brake`).

**지시등 깜빡임 보정**
- `turnSignal`이 램프 상태(깜빡일 때마다 ON/OFF)로 올 수 있다. 그래서 같은 방향 `LEFT`/`RIGHT` 사이에 낀 `OFF`(또는 `null`)가 **1.5초 이하**면 하나로 이어진 켜짐으로 본다 (D4 확정). 사이에 반대 방향이 켜졌으면 잇지 않는다.
- 켜짐이 규칙 구간 앞에서부터 이어졌으면 켬 시작은 구간 시작 시각으로 자른다.
- 100ms 샘플링이면 깜빡임(보통 1~1.5Hz)이 기록에 그대로 보일 수 있어서 이 보정이 필요하다.
- 실차에서 레버 상태(깜빡임 없음)로 확인되면 보정을 빼도 된다. 빼지 않아도 결과는 같다.

### 4.2 후진 `reverse_v0`

| 항목 | 규칙 |
|---|---|
| 대상 키 | `parties.ego.movement` = `reverse` |
| 확정 (자동 답변) | `state(gear, T) = R`이고, 구간 `[-3000, 0]`의 60% 이상이 `R` (분모는 구간 길이 3초, `null`인 시간은 R이 아님). hard_brake 제외 구간은 적용하지 않음 |
| 근거 문장 | "사고 직전 3초 중 2.4초 동안 기어가 R(후진)이었어요" |
| 그 밖 | `[-3000, 0]`에 `R`이 있었지만 위 조건이 아니면 `movement` 질문에 `model_guess: reverse`와 근거만 붙임. 사고 때 R이 아니면 "사고 2초 전까지 후진 기어였어요", 사고 때 R이지만 60% 미만이면 "사고 직전 3초 중 1.7초 동안 기어가 R(후진)이었어요" |
| 함께 넣는 사실 | 특수 상황 보기 `reverse:ego`는 이 답으로 이미 반영되므로 질문 보기에서 미리 고른 상태로 둠: `situation.special` 질문의 `model_guess`에 더하고 `guess_source: "vehicle"`. 판정에는 넘기지 않음 (진행 방향 `reverse`가 출처 `vehicle`로 넘어가므로. 사용자 답 경로로 넘기면 출처가 `user`가 되어 "입증 필요"가 붙음) |

### 4.3 진행 방향 `movement_v0`

- 위치 궤적이 없으면 회전 여부를 **확정할 수 없다.** 그래서 v0는 후진(4.2)만 자동 답변하고, 나머지는 **추정값만** 준다.

| 조건 (위에서부터 처음 맞는 것) | `model_guess` | 근거 문장 |
|---|---|---|
| 후진 확정 (4.2) | (자동 답변 `reverse`) | |
| 후진 추정 (4.2 "그 밖") | `reverse` | 4.2 "그 밖"의 문장 |
| `[-8000, -1500]`에 `LEFT`와 `RIGHT`가 **둘 다** 1초 이상 켜짐 | `null` (D14 확정). 아래 "서 있었음" 조건이 맞으면 `stationary_at_collision = true`는 함께 넘김 | "양쪽 지시등이 함께 켜졌어요(비상등 가능성)" |
| `[-8000, -1500]`에 `LEFT`가 1초 이상 켜짐 | `left_turn` | "사고 N초 전부터 왼쪽 지시등이 켜져 있었어요" |
| `[-8000, -1500]`에 `RIGHT`가 1초 이상 켜짐 | `right_turn` | 위와 같음 (RIGHT) |
| `[-3000, 0]` 내내 속도 ≤ 2km/h이고 기어가 `P`/`N`/`D` (속도·기어가 내내 `null` 아님) | `null`. 대신 사실 `stationary_at_collision = true`를 질문 없이 판정에 넘김 (D7 확정, 출처 `vehicle`) | "사고 때 내 차는 서 있었어요" |
| `[-8000, 0]`에 지시등이 한 번도 안 켜졌고(`turnSignal`이 모두 `null`이면 아님) 평균 속도 ≥ 15km/h | `straight` | "사고 전 8초 동안 지시등을 켜지 않고 달렸어요" |
| 그 밖 | `null` | |

- **지시등 방향은 "왼쪽 회전·유턴·왼쪽 차로 변경"을 구분하지 못한다.** 그래서 추정값일 뿐이고 사용자가 고친다.
- 지시등 구간 `[-8000, -1500]`은 `manual`이어도 -1.5초에서 자른다.
- 추정값이 없는 줄의 근거 문장("서 있었어요", "양쪽 지시등")은 `guess_evidence`에 담는다 (3절).

### 4.4 방향지시등 `turn_signal_v0`

| 항목 | 규칙 |
|---|---|
| 대상 키 | `parties.ego.turn_signal_used` |
| 계산 조건 | 내 차 진행 방향(사용자 답 또는 자동 답변)이 `left_turn` / `right_turn` / `u_turn` / `lane_change`일 때만. 진행 방향이 정해지지 않으면 계산하지 않음 (질문도 기존 조건대로 안 나옴). 자동 답변은 지시등 질문이 나올 때만 씀 (2.6) |
| 기대 방향 | `left_turn`·`u_turn` → `LEFT`, `right_turn` → `RIGHT`, `lane_change` → `parties.ego.lane_change_dir` 답이 있으면 그 방향, 없으면 둘 다 |
| 보는 구간 | `manual`: `[-10000, 0]`. `hard_brake`: **`[-10000, -1500]`** (4.1 충돌 직전 제동 구간 제외, D13 확정) |
| 켬 시작 `onset` | 보는 구간 안에서 기대 방향의 **마지막으로 이어진 켜짐**이 시작된 시각 (깜빡임 보정 후) |
| `true` (켰음) | `onset ≤ T - LEAD`이고 그 켜짐이 1초 이상 이어짐 (`LEAD`는 아래 행) |
| `false` (안 켰거나 늦게) | 보는 구간에 기대 방향 켜짐이 없음 → 근거 "사고 전 10초 동안 오른쪽 지시등을 켜지 않았어요" (진로 변경이고 방향 답이 없으면 "사고 전 10초 동안 지시등을 켜지 않았어요"). `onset > T - LEAD` → 근거 "사고 1.2초 전에야 오른쪽 지시등을 켰어요". 반대 방향만 켜짐 → 근거 "오른쪽이 아니라 왼쪽 지시등을 켰어요". `onset ≤ T - LEAD`지만 1초 미만 → 근거 "사고 6초 전 오른쪽 지시등을 0.6초만 켰어요" |
| `false` (hard_brake 제외 구간에만 켬) | `hard_brake`이고 보는 구간에는 지시등이 전혀 없는데 `[-1500, 0]`에 기대 방향이 켜짐 → 근거 "사고 직전 1.5초 안에만 켜져 판단에서 제외했어요" (D13). 보는 구간에 반대 방향이 켜졌으면 반대 방향 근거가 먼저 |
| `true` 근거 | "사고 3.2초 전 오른쪽 지시등 켜짐 (사고 때까지 켜져 있음)". 보는 구간 끝 전에 꺼졌으면 "(3초 동안)" |
| `LEAD` (D3 확정) | **`LEAD = clamp(30m ÷ v_avg, 2초, 5초)`**. 일반도로는 회전하려는 지점 30m 앞에서 켜야 하는 것(도로교통법 시행령)을 시간으로 바꾼 것 |
| `v_avg` | 구간 `[-5000, -1500]`의 평균 속도를 m/s로 바꾼 값 (`hard_brake`면 직전 1.5초 제동 구간을 빼려고 끝을 `-1500`, `manual`이면 `[-5000, -500]`). 기록이 빈 구간은 평균에서 뺌 |
| `LEAD` 예 | 20km/h(5.6m/s) → 5.4초 → **5초** / 30km/h → **3.6초** / 50km/h → **2.2초** / 60km/h 이상 → **2초**. `v_avg < 1km/h`(거의 서 있음)면 **5초** |
| `LEAD` 근거 문장 | 판정에 쓴 `LEAD`도 근거에 넣음. 예: "사고 1.8초 전에야 오른쪽 지시등을 켰어요 (평균 32km/h라 3.4초 전에는 켜야 해요)" |
| `undetermined` | 보는 구간에 2초 넘는 빈 곳, `turnSignal`이 모두 `null`("사고 전 지시등 기록이 없어요"), 또는 `v_avg` 구간의 속도가 모두 `null`이라 `LEAD`를 못 정함("사고 전 속도 기록이 없어 지시등을 언제까지 켜야 했는지 알 수 없어요") |
| 한계 | 기준이 실제 "회전 시작"이 아니라 `T`(사고 시각)라서, 회전이 사고보다 한참 앞서 시작됐으면 늦게 켠 것을 "켰음"으로 볼 수 있음 (너그러운 쪽). 위치 궤적이 생기면 회전 시작 시각으로 바꿈 |

### 4.5 진입 전 서행 `slowed_v0`

| 항목 | 규칙 |
|---|---|
| 대상 키 | `parties.ego.slowed_before_entry` |
| 계산 조건 | 장소가 교차로이고 신호 없음일 때만 (서행 질문이 나오는 조건과 같음). **`road.signal_present`에 답이 없으면 기본값(없음, `false`)으로 본다** (판정에도 그 값을 쓰므로). 신호 있음(`true`)으로 답하면 서행 자동 답변을 `auto_answers`에도 판정에도 넣지 않음. 규칙 함수(`rules.slowed`)는 늘 계산하고, 이 조건은 어댑터가 본다 |
| 진입 시각 | 위치 데이터가 없어서 모름. **v0는 "충돌 1.5~3초 전에 진입"으로 가정**하고 아래 구간을 씀. 아래 `true`/`false` 조건이 분명할 때만 자동 답변하고, 나머지는 추정값으로 질문 (D5 확정) |
| 구간 | 비교 기준 `REF = [-6000, -3000]`, 진입 직전 `PRE = [-3000, -1500]` (`hard_brake`면 `[-1500, 0]`은 뺌, `manual`이면 `PRE = [-3000, -500]`) |
| 값 | `v_ref` = `REF`의 최고 속도, `v_pre` = `PRE`의 최저 속도, `brake_pre` = `PRE`에서 브레이크를 밟은 시간. `PRE`의 `brake`가 모두 `null`이면 `brake_pre`는 모름 → 아래 브레이크 조건(`≥ 0.5초`, `= 0`)을 만족하지 않음 |
| `true` + 정지 | `PRE`에서 0.5초 이상 속도 ≤ 3km/h → `slowed_before_entry = true`, `stopped_before_entry = true`도 질문 없이 함께 넘김 (D7 확정). 근거 "진입 전 0.8초 동안 멈췄어요" |
| `true` (서행) | `v_pre ≤ 15km/h`, 또는 (`v_pre ≤ 0.7 × v_ref`이고 `brake_pre ≥ 0.5초`). 근거 "사고 3초 전 38km/h → 직전 21km/h로 줄였어요 (브레이크 1.1초)". "3초 전"은 `REF`에서 최고 속도가 마지막으로 유지된 끝 시각. 브레이크가 0이면 괄호를 뺌 |
| `false` | `brake_pre = 0`이고 `v_pre ≥ 0.9 × v_ref`이고 `v_pre ≥ 20km/h`. 근거 "사고 직전까지 브레이크 없이 40km/h 안팎으로 달렸어요" ("안팎" = `PRE` 평균 속도) |
| 그 밖 | `undetermined`. 질문에 `model_guess`(`v_pre < v_ref`면 `true`, 아니면 `false`)와 근거(위 `true`·`false` 문장 형식)를 붙임 |
| 함께 남기는 값 | `intersection_entry_speed_kmh` = `PRE` 시작 시점 속도. 판정 엔진은 제한속도(`speed_limit_kmh`)가 있어야 쓰므로 v0 판정에는 영향 없음. 기록만 함 |
| 한계 | 진입 시각을 가정한 규칙이라, 진입 후 한참 달려 부딪힌 사고(큰 교차로, 회전 중 충돌)는 잘못 볼 수 있음 |

### 4.6 그 밖 (자동 답변 없이 바로 채우는 값)

| 값 | 규칙 |
|---|---|
| `parties.ego.cls` | 요청의 `vehicle.cls` (없으면 `car`). 출처 `vehicle` |
| `parties.ego.entry_from` | `south` 고정 (2.6 방위 변환). 질문하지 않음 |
| `parties.ego.lane_change_dir` | 진행 방향이 `lane_change`이고 `[-8000, -1500]`에 한쪽 지시등만 켜졌으면(최소 시간 없음) 그 방향. 자동 답변 (`lane_change_dir_v0`). 근거 "사고 6초 전 왼쪽 지시등을 켰어요" |

## 5. 인증

**목표 (v1 이후, 초안)**
- 차량 앱은 소셜 로그인 화면을 띄우기 어렵고(운전 중, 차량 OS), 기기가 계정보다 오래 산다. 그래서 **기기 단위 토큰**을 쓴다.
- **등록**:
  - 앱이 처음 켜질 때 `POST /api/devices` `{"device_id", "model"}`를 보내고 `{"device_token"}`을 받는다 (길게 유효, 회전 가능).
  - 사람 계정에 연결하려면 휴대폰 앱에서 연결 코드를 입력한다 (기기 ↔ 회원).
- **요청**: `Authorization: Device <device_token>` 헤더를 쓴다. 차량 사건의 주인은 기기이고, 연결된 회원이 있으면 그 회원의 보관함에도 보인다.
- **세부 미정**: 토큰 폐기·분실, 차량 판매 시 연결 해제, 한 차를 여러 사람이 쓸 때.

**v0 데모 (지금 있는 것으로)**
- **기존 dev 로그인을 그대로 쓴다.** 서버 `.env`에 `MTM_DEV_LOGIN=1`이 있어야 한다.
  1. `POST /api/auth/dev` `{"token": "vehicle-<기기 식별 문자열>"}` → `{access, refresh, user}`
  2. 처음 한 번 `PUT /api/me` `{"nickname": "차량1", "agree_terms": true}`
     - 기존 API는 가입이 끝나지 않으면 `403 signup_required`를 돌려주는데, 차량 사건 주소도 같은 검사를 쓴다고 가정한다.
  3. 그 뒤 모든 요청에 `Authorization: Bearer <access>`. access가 만료되면(30분) `POST /api/token/refresh`
- dev 로그인은 토큰 문자열이 곧 회원 식별자라서 **아무나 같은 이름으로 로그인할 수 있다.** 그래서 데모 밖에서는 쓰지 않는다.

**탈퇴 때 삭제**
- 기존 `DELETE /api/me`(탈퇴)가 `204`로 끝나면 그 회원의 차량 사건도 모두 지운다 (samples 포함). 탈퇴가 실패하면(401 등) 지우지 않는다.
- 탈퇴 뒤에는 토큰의 회원을 찾을 수 없으므로, 서버는 탈퇴 요청 전에 회원 id를 알아 둔다 (8.3 미들웨어). 경로는 정확히 `/api/me`만 본다.
- 남은 위험: 탈퇴는 끝났는데 차량 사건 삭제가 DB 오류로 실패하면 응답은 `500`이고 주인 없는 차량 사건이 남을 수 있다. 순서를 바꾸면(먼저 삭제) 탈퇴가 실패했을 때 차량 사건만 사라지므로, 개인정보 쪽으로 덜 나쁜 지금 순서를 쓴다.

## 6. 시각 형식

### 6.1 epoch 밀리초로 통일

- 이 문서의 새 주소는 요청·응답의 **모든 시각을 epoch 밀리초 정수**(UTC 기준 1970-01-01부터의 ms)로 쓴다.
  - 대상: `range`, `t_event`, `samples[].t`, `created_at`, `updated_at`, `evidence.window`, `evidence.points[].t`
- 기존 API는 그대로다. 혼용 상태는 현황 0절에 있다.
  - 사건 `created_at`·`delete_at`: ISO 문자열
  - 글 `created_at`·목록 `before`: epoch **초**(float)
- **기준 시계**: `samples[].t`와 `t_event`는 **앱(차량) 시계**다. 서버는 이 값을 자기 시계와 비교하지 않는다. 다만 서버 시각과 하루 넘게 다르면 `data_quality.clock_warnings`에 경고를 남긴다(오류는 아님, 2026-11-11 구현).
  차량 사건은 기록 구간(`range`)에서 서버가 받은 시각에 가장 가까운 끝을 본다: `[{"kind": "vehicle_clock", "source": "app", "t_ms", "server_ms", "diff_ms", "direction": "ahead"|"behind", "message"}]`, 없으면 `[]`.
  블랙박스 사건은 영상 촬영 시각(`video_clock`)도 본다 (`docs/design-blackbox.md` 3.6 "시각 맞추기"). 앱은 아직 이 경고를 보여 주지 않는다. 사건의 `created_at`·`updated_at`은 서버 시계다.
- **기간 값**: 응답에 나오는 "N초 전" 같은 기간은 사람이 읽을 근거 문장(`evidence.text`)에만 쓴다. 기계가 읽는 값은 늘 ms 시각으로 준다.

### 6.2 기어 값 (앱 쪽 변환)

- 앱은 기어를 Android `VehicleGear` **정수**로 기록한다 (`VehicleSnapshot.gear: Int?`, 루프 CSV에는 `"8"` 같은 정수 문자열).
- 이 API는 **문자열만** 받으므로(D8 확정), 앱이 올리기 전에 아래 표대로 바꾼다. 정수를 보내면 `sample_invalid`.

| `VehicleGear` | 값 | API |
|---|---|---|
| `GEAR_PARK` | 4 | `P` |
| `GEAR_REVERSE` | 2 | `R` |
| `GEAR_NEUTRAL` | 1 | `N` |
| `GEAR_DRIVE` | 8 | `D` |
| `GEAR_FIRST`~ (수동 단수 16, 32, …) | | `D` |
| `GEAR_UNKNOWN` | 0 | `null` |

- `turnSignal`은 Pleos `TurnSignal` 값을 `toString()`한 것이다. 실제 문자열이 `LEFT`/`RIGHT`/`OFF`인지 실차에서 확인해야 한다. 다르면 앱에서 맞춰 바꾼다.

## 7. 미정 사항

| 항목 | 지금 | 남은 일 |
|---|---|---|
| **위치·교차로** | `location`은 `null`만 받음. 진입 시각·회전 여부·신호 유무·도로 폭을 모름 | 위치 궤적 형식(`[{t, lat, lon, heading, accuracy}]`), 지도 매칭(교차로 위치, 신호 유무, 도로 폭, 제한속도)을 앱과 서버 중 어디서 할지. 생기면 `movement`(회전 확정), `slowed_before_entry`(실제 진입 시각), `road.signal_present`, `road.wider_road`, `speed_limit_kmh`(과속 가감)를 자동 답변으로 올림 (현황 6.3). 위치는 개인정보라 보관 기간·암호화도 정해야 함 |
| **블랙박스 영상 연결** | 차량 사건은 영상 없음. 블랙박스 분석은 서버에 없음 (현황 7절) | 연결 방식 후보: (가) `POST /api/vehicle-cases/{id}/video`로 영상 추가, (나) 기존 `POST /api/cases`에 `vehicle_case_id`를 받기. 어느 쪽이든 영상 시각과 차량 기록 시각 맞추기(오프셋), 블랙박스 영상에서는 촬영 차가 곧 `ego`라는 대응, 모서리 단계 대체(현황 7.2)가 필요 |
| **비상등·전조등** | `turnSignal`은 LEFT/RIGHT/OFF뿐이라 비상등을 못 나타냄. 전조등 값은 수집하지 않음 | Pleos·CarPropertyManager에서 비상등(`HAZARD`)·전조등 상태를 받을 수 있는지 확인. 받으면 `samples`에 `hazard`, `headlight` 칸 추가 → 특수 상황 `hazard`(서 있을 때 비상등), `no_lights`(밤에 전조등 안 켬)를 자동 답변으로 |
| 사건 관리 | 삭제(`DELETE`)는 v0에 있음. 목록·보관함·보관 기간은 없음 | 기존 `/api/cases`처럼 7일 자동 삭제 + 보관함으로 할지, 기록은 더 짧게 둘지 |
| 탈퇴 시 삭제 | **완료 (v0.3).** `install(app)`의 미들웨어로 탈퇴 뒤 차량 사건을 지움 (5절, 8.3). MTM 수정·패치 없음 | — |
| 가감 요소 출처 이름 대응 | 사실 이름이 질문 키와 다르면(`entry_lead_sec` ← `intersection_entry_order`) `modifiers[].source`가 `default`로 나옴 (2.7) | 사실 이름 → 질문 키 대응표를 둘지 |
| 시계 차이 경고 | **서버 완료 (2026-11-11).** `data_quality.clock_warnings` (6.1) | 앱 표시 (UI 작업 때) |
| 투표 게시판 | 차량 사건은 글로 못 올림 | 그림이 없는 사건의 글 형식 |
| 기록 업로드 크기 | 120초, 20,000개 제한 (임시). 100ms 샘플링이면 120초에 약 1,200개라 여유가 큼 | 실제 운영에서 필요한 구간 길이를 보고 줄임 |
| 상대 차 기록 | 없음 (상대 값은 모두 사용자) | 상대도 HMTM 앱을 쓰면 두 기록을 합칠 수 있는지 (먼 미래) |

## 8. 구현 메모 (참고, 명세 아님)

### 8.1 코드 영역 원칙

| 영역 | 경로 | 원칙 |
|---|---|---|
| MTM에서 가져온 코드 | `backend/src/app/`, `backend/src/analyze/`, `backend/src/server/`, `backend/judge/` 등 | **직접 수정하지 않는다.** 불러 쓰기만 한다 |
| 새 차량 사건 코드 | `backend/src/vehicle/` | 이번 작업의 코드는 모두 여기 |
| 서버 연결 | `backend/src/server/app.py` | **연결 한 줄만** 추가 (8.3) |
| 어쩔 수 없는 MTM 수정 | `docs/patches/` | 어댑터로 안 되는 경우에만 고치고, 그 변경을 패치 파일로 보관 (8.5) |

### 8.2 `src/vehicle/` 구성 (안)

| 파일 | 하는 일 |
|---|---|
| `api.py` | **구현됨.** 라우터(`APIRouter`, 접두어 `/api/vehicle-cases`)와 `install(app)`. 2절의 4개 주소(POST·PUT·GET·DELETE). 인증은 `src.server.auth.user_of`(가입까지 끝난 회원)를 그대로 불러 씀. 탈퇴 미들웨어 `delete_on_withdraw` (5절) |
| `samples.py` | **구현됨.** 요청 검사 `validate(body)`(2.1 오류 코드, 실패하면 `VehicleError(code, message)`), 유지 방식 `Timeline`(`state`, `gaps`, `has_gap` 등), 깜빡임 보정 `signal_intervals` |
| `rules.py` | **구현됨.** 자동 답변 규칙 v0 (4절) 5개와 `run_rules`. 아래 "규칙 결과 모양" |
| `adapter.py` | **구현됨.** MTM 함수에 넣을 **facts 껍데기**를 만들고 결과를 차량 사건 모양으로 바꿈 (8.4). `build(request, answers)`가 규칙·질문·답 검사·판정을 한 번에 돌림 (POST·PUT 모두) |
| `store.py` | **구현됨.** `vehicle_cases` 표 `create`·`get`·`update`·`delete`·`delete_owner`(탈퇴) |

**규칙 결과 모양 (`rules.py`)**
- 정함: `{"field", "value", "source": "vehicle", "rule", "evidence": {"text", "window", "points"}, "determined": true, "facts", "params"}`
- 못 정함: `{"field", "rule", "determined": false, "value": null, "model_guess", "guess_source", "guess_evidence", "facts", "params"}`
- 해당 없음(예: 진행 방향이 회전이 아닐 때의 지시등, R이 없을 때의 후진): `None`
- `facts`: 질문 없이 판정에 넘길 사실 (`stopped_before_entry`, `stationary_at_collision`, `intersection_entry_speed_kmh`). 모두 출처 `vehicle`.
- `params`: 계산값 (`lead_ms`, `v_avg_kmh` 등). 저장·설명용.
- 후진 확정 결과에는 `preselect: {"situation.special": ["reverse:ego"]}`가 더 붙는다 (4.2).
- `auto_answer(결과)`는 3절 자동 답변 모양(`field`, `value`, `source`, `rule`, `evidence`)만 남긴다.

**`run_rules(tl, ctx, answers)`**
- `Timeline(samples, end=range.to)`, `Ctx(t_event, t_event_source)`, 사용자 답 `{field: value}`를 받아 규칙 결과 목록을 돌려준다.
- 순서: 진행 방향(`movement_v0`, 후진 포함) → 진로 변경 방향 → 지시등 → 서행.
- 사용자 답이 있으면 자동 답변보다 우선해 다음 규칙의 입력이 된다 (D9). 진행 방향은 **사용자 답 또는 자동 답변(후진)일 때만** 지시등·진로 변경 방향 계산에 쓰고, 추정값은 쓰지 않는다 (4.4 계산 조건).
- 서행 질문 조건(교차로·신호 없음)은 보지 않는다. 어댑터 몫.

### 8.3 서버 연결 (app.py에 추가할 한 줄)

```python
from src.vehicle.api import install as install_vehicle; install_vehicle(app)   # 차량 사건 API (docs/api-spec.md)
```

- **위치**: `app.py` 맨 끝. `app`과 예외 처리기가 모두 정의된 뒤라야 한다.
- **`install(app)`이 하는 일**:
  - `app.include_router(router)`
  - 차량 사건 오류(`VehicleError`)를 `{"error", "message"}` 모양으로 바꾸는 예외 처리기 등록. `APIRouter`에는 예외 처리기를 달 수 없어서 여기서 함.
  - 탈퇴 미들웨어(`api.delete_on_withdraw`) 등록: `DELETE /api/me` 요청이면 먼저 토큰의 회원 id를 알아 두고, 응답이 `204`일 때만 `store.delete_owner`로 차량 사건을 지움 (5절). `delete_me`는 고치지 않음.
- **순환 import를 피하려고 `src.server.app`을 import하지 않는다.** `app.py`가 `src.vehicle.api`를 부르므로, 반대 방향으로 부르면 순환이 생긴다. 그래서:
  - 인증 의존성: `src.server.auth.user_of`와 FastAPI `HTTPBearer`로 `api.py`에서 다시 만든다 (`app.py`의 `me`와 같은 동작).
  - 인증 오류(`AuthError`): 기존 처리기가 앱 전체에 걸려 있어 그대로 같은 모양으로 나간다.

### 8.4 MTM 함수 재사용 (어댑터)

- **방식**: 어댑터가 영상 전용 입력을 빈 값으로 채운 facts 껍데기를 만들고 MTM 함수를 그대로 부른다.

```python
facts = {
  "schema_version": "0.3", "video": None, "fps": 10,
  "collision": {"a": "ego", "b": "other", "frame": 0, "t": 0, "zone": "intersection"},  # 영상 전용 값은 0·고정값
  "parties": {"ego":   {"cls": …, "movement": …, "entry_from": "south", …},
              "other": {"cls": …, "movement": …, "entry_from": …}},
  "road": {"location": …, "junction_type": …, "signal_present": …, "road_width": …},
  "unknowns": [ … ],
}
```

| MTM 함수 | 용도 | 확인 결과 (2026-11-08, 코드 수정 없이 위 껍데기로 호출) |
|---|---|---|
| `src.app.situation.questions(facts, user)` | 상황 질문 목록 | **동작함.** 일시정지 표지, 서행, 지시등, 진입 확실성, 특수 상황, 운전자 요인 등이 나옴. 영상 전용 키(`evidence_frame`, `image`)는 어댑터가 응답에서 지움. 영상 전용 질문(바닥 화살표 `lane_marking`)도 어댑터가 뺌 |
| `src.app.answers.to_assumptions(facts, user)` | 답 → 판정 가정 | **동작함.** `intersection_entry_order` → `entry_lead_sec ±0.5`, 당사자 답(`turn_signal_used` 등) 반영 확인 |
| `src.app.judge_bridge.judge(path, asm, judge_dir)` | 판정 | **동작함.** 당사자 id `ego`/`other`, 출처 `vehicle` 값으로 `차13-1 오른쪽 우회전 대 왼쪽 직진 (동일폭)`, `{ego: 60, other: 40}`. 판정 엔진 수정 불필요 |
| `src.app.answers.check`, `remaining`, `fill_guesses` | 답 검사, 남은 질문, 기본값 채우기 | **동작함** (2026-11-09, 같은 껍데기로 호출). `check`는 자기 차 기준 보기의 질문으로 돌림. `fill_guesses`가 판정 facts의 장소를 비우므로 가정(`to_assumptions`)은 원래 facts로 만듦 |

**어댑터가 꼭 해야 할 일**
- **기본값 채우기**: 도로 폭 같은 기본값 질문을 빈칸으로 두면 판정 엔진이 "맞는 규칙 없음"을 낸다. 위 확인에서 `road_width`가 없을 때 그랬다. 그래서 기존 흐름(`fill_guesses`)처럼 기본값(`equal`)을 채워 넘겨야 한다.
- **보기 변환 (2.6 ★)**: 자기 차 기준 보기(`left`/`right`/`opposite`/`same`, `mine`/`theirs`)는 MTM 함수에 넘기기 **전에** 동서남북 값으로 바꾼다. `answers.check`는 질문의 `options`로 검사하므로, 검사는 어댑터가 자기 보기로 먼저 하고 MTM에는 변환된 값만 넘긴다.
- **출처 붙이기**: 자동 답변은 facts 값 객체에 `source: "vehicle"`로 넣는다. 사용자 답은 `to_assumptions` 경로로 넘긴다 (판정 엔진이 `user`로 표시).

### 8.5 MTM 수정이 필요할 수 있는 곳 (패치 후보)

| 곳 | 이유 | 대응 |
|---|---|---|
| `src/server/app.py`의 `delete_me` (탈퇴) | 차량 사건을 모름. 탈퇴해도 `vehicle_cases`가 남음 | **미들웨어로 해결, 패치 없음** (8.3). `docs/patches/`는 만들지 않음 |
| `src/app/answers.py`의 질문 검사 | 차량 사건 전용 키(`scene.place`, `scene.junction_type`)를 모름 | 어댑터가 MTM에 넘기기 전에 이 키를 빼고 facts의 `road`로 옮겨서 피함 (**수정 불필요 확인**) |

**패치 보관 규칙 (`docs/patches/`)**
- **이름**: `<날짜>_<대상 파일>_<이유>.patch`
- **만드는 법**: `git diff` 결과를 저장한다.
- **패치마다 적을 것**: 같은 이름의 `.md`에 왜 어댑터로 안 됐는지, MTM 원본의 어느 판(`docs/origin.md`)에 대한 패치인지.

### 8.6 저장

- **표 `vehicle_cases` 하나**:
  - 요청 원본(samples 포함), 답, 자동 답변, 결과 JSON을 둔다.
  - 규칙 버전(`rule`)과 `judge_version`을 함께 남겨, 나중에 규칙을 바꿔도 예전 결과를 설명할 수 있게 한다.
- **기존 DB 파일을 같이 씀**:
  - 기존 `src.server.db.connect()`로 같은 SQLite 파일을 연다.
  - 표는 `store.py`가 `CREATE TABLE IF NOT EXISTS`로 만든다. `db.py`는 고치지 않는다.
- **삭제**: `DELETE`는 행 하나를 지우면 끝나도록 samples를 따로 파일로 두지 않는다.

## 9. 결정 사항

v0 초안에서 "결정이 필요한 것"으로 올린 12개를 v0.1에서 모두 확정했다 (2026-11-08). D13~D14는 규칙 구현 중 나온 것으로 v0.2에서 확정했다 (2026-11-09). 그 밖의 세부 확정은 `docs/vehicle-rules-v0-notes.md` (API 구현 세부 C1~C14, E1~E11은 v0.3 본문에 반영).

| # | 결정할 것 | 초안의 선택 | 다른 선택지 | **확정** |
|---|---|---|---|---|
| D1 | 상대 방향을 **자기 차 기준 보기**(`left`/`right`/`opposite`/`same`)로 받고 자기 차를 남쪽 진입으로 고정 | 이 방식 | 동서남북 그대로 묻기 (사용자가 답하기 어려움) | **초안대로** (2.6) |
| D2 | `t_event`의 뜻: 급제동 시각인가, 충돌 순간인가 | `hard_brake`면 급제동 감지 시각으로 보고 직전 1.5초를 뺌. `manual`이면 충돌 순간 | 앱에서 북마크 뒤 "부딪힌 순간"을 꼭 고르게 하기 | **초안대로** (4.1) |
| D3 | 지시등 "늦게 켬" 기준 `LEAD` | 3초 고정 | 속도 기준 `30m ÷ 속도` (2~5초) | **속도 기준 `LEAD = clamp(30m ÷ 평균 속도, 2초, 5초)`** (4.4) |
| D4 | `turnSignal`이 레버 상태인지 깜빡이는 램프 상태인지 | 1.5초 이하 끊김은 이어진 것으로 보정 | 확인 후 보정 제거 | **초안대로** (4.1). 실차 확인은 계속 할 일 |
| D5 | 위치 없이 진입 시각을 "충돌 1.5~3초 전"으로 가정해 서행을 자동 답변할지 | 자동 답변함 (조건이 분명할 때만) | v0는 추정값만 주고 늘 사용자에게 확인 | **초안대로** (4.5) |
| D6 | 차량 기록으로 적용된 가감 요소를 **입증된 것**으로 볼지 | 판정 엔진 그대로 (입증 필요 표시 없음) | `vehicle`도 "기록 제출 필요" 같은 별도 표시 | **초안대로** (2.7) |
| D7 | 서 있었음(`stationary_at_collision`)·정지(`stopped_before_entry`)를 질문 없이 사실로 넘길지 | 넘김 (속도 ≤ 2~3km/h 조건) | v0 범위만 하고 나머지는 질문 | **초안대로** (4.3, 4.5) |
| D8 | 기어를 문자열(`P/R/N/D`)로만 받을지, `VehicleGear` 정수도 받을지 | 문자열만 (앱에서 변환) | 둘 다 받기 | **초안대로** (6.2) |
| D9 | 사용자가 자동 답변과 다르게 답하면 | 사용자 답 우선 + `answer_conflicts`에 기록 | 자동 답변 고정, 또는 고칠 때 이유 받기 | **초안대로** (2.2) |
| D10 | 답하기 전에 임시 결과(비율)를 보여 줄지 | 보여 줌 (`provisional: true`) | 질문을 다 답할 때까지 결과를 숨김 | **초안대로** (2.5, 2.7) |
| D11 | 차량 사건에서 기존 기능(삭제·보관함·7일 자동 삭제·투표)을 언제 붙일지 | v0에는 없음 | v0부터 삭제만이라도 (개인정보) | **v0에 `DELETE /api/vehicle-cases/{id}` 추가** (samples 포함 전부 삭제, 2.4). 보관함·자동 삭제·투표는 7절 미정 |
| D12 | 기기 토큰 도입 시점과 계정 연결 방식 | v0는 dev 로그인, v1에 기기 토큰 | 처음부터 기기 토큰 | **초안대로** (5절) |
| D13 | hard_brake일 때 지시등 구간 (4.1은 직전 1.5초 제외, v0.1 4.4 표는 `[-10000, 0]`) | 4.1대로 제외 | 4.4대로 `[-10000, 0]` | **4.1대로 `[-10000, -1500]`**. 제외 구간에만 켜졌으면 근거 "사고 직전 1.5초 안에만 켜져 판단에서 제외했어요", 결과 `false` (4.4) |
| D14 | 좌우 지시등이 둘 다 1초 넘게 켜졌을 때의 진행 방향 추정 | 표 순서대로 LEFT | 나중에 켠 쪽 | **추정하지 않음**. 근거 "양쪽 지시등이 함께 켜졌어요(비상등 가능성)" (4.3) |
