# 블랙박스 사건 설계 (영상 기본 + 차량 기록 보강) — v0.1, 분석기 출력 bb-0.2

> **일부 내용은 구현과 다를 수 있음, 최신은 [README](../README.md).** 개발 중에 쓴 설계 문서로, "차량 기록은 참고 자료" 결정 이전 내용이 섞여 있다. 본문에 나오는 `*-notes.md`, `api-current.md`, devlog, CLAUDE.md는 내부 작업 기록이라 이 저장소에 넣지 않았다.

> 상태: **설계 v0.1** · 2026-11-09. 9절 결정 Q1~Q17 중 15개 확정, Q2·Q14는 대기(기본안으로 진행).
> 변경: 초안(2026-11-09, PR #11) → 7.1 USB 저장장치 조사 추가 → v0.1 결정 반영(9절 "확정" 열, 본문 해당 절)
> → **분석기 출력 bb-0.2** (2026-11-10): 상대 종류(`cls`)를 판정 엔진의 사고 장 고르기와 맞춤, 보행자·자전거 사고 항목과 횡단보도 거리 4구간 추가(8.3.1~8.3.3),
> 8절 필드 목록을 `backend/judge/docs/A_REQUESTS.md`(hmtm-0.1.1, 2026-11-10)의 "채울 곳 = 영상·모델" 항목과 맞춤, 가짜 분석기 보행자·자전거 시나리오 계획(2.4).
> → **bb-0.2 구현** (2026-11-10, `feature/bb-ped-bike`): 검사표 bb-0.2(bb-0.1도 받음), 내 차 신호 이름을 판정 엔진 이름으로 통일, 상대 종류로 사고 장 고르기(`src/blackbox/chapter.py`), 보행자·자전거 장 질문, 시나리오 2개, 결과 비율 표기(3.6). 설계와 다르게 한 점: `docs/bb-ped-bike-notes.md`.
> 읽은 문서: `docs/api-current.md`(이하 "현황"), `docs/api-spec.md` v0.3(이하 "차량 명세"), `docs/vehicle-rules-v0-notes.md`(이하 "notes"), `backend/judge/docs/FACTS_SPEC.md`(이하 "FACTS").
> 읽은 코드: `backend/src/analyze/ego_motion.py`, `lead_vehicle.py`, `bb_signal.py`, `backend/tools/blackbox_tracks.py`, `val_bb_signal.py`, `backend/judge/adapter.py`, `fault_engine.py`(출처 처리), `backend/src/vehicle/*`, `android/app/src/main/`.
> 표시: **(확인 필요)** = 코드·문서로 확인하지 못해 실물·실차로 확인해야 하는 것. **(확정 Qn)** = 9절에서 확정한 결정. **(제안)** = 아직 결정하지 않은 이 문서의 안. 결정은 9절에 모았다.

## 0. 바뀐 설계 방향

| 항목 | 지금까지 (차량 명세 v0.3) | 바뀐 방향 |
|---|---|---|
| 기본 입력 | 차량 기록만 (`/api/vehicle-cases`, 영상 없음) | **블랙박스 영상이 꼭 있어야 함**. 차량 기록은 있으면 붙이는 보강 |
| 영상 종류 | 없음 (CCTV 연결은 7절 미정이었음) | **블랙박스만**. CCTV는 HMTM에서 지원하지 않음 |
| 당사자 | `ego` = 앱이 깔린 차, `other` = 상대 | 같음. **카메라 차 = 내 차 = `ego`** (CCTV처럼 "어느 궤적이 내 차인가"를 고를 필요가 없음, 현황 6.2 전제 2가 사라짐) |
| 영상 분석 | 없음 | MTM이 블랙박스 분석기를 개발 중. HMTM에는 **입출력 모양만 정한 빈자리**를 두고, 지금은 **가짜 분석기**로 나머지를 완성함. MTM이 끝나면 그 자리만 바꿈 |

**이 방향에서 지금 코드가 그대로 맞는 점**
- 차량 사건이 이미 `ego`/`other` 고정 이름, "내 차는 남쪽에서 북쪽으로 들어왔다" 고정(D1), 자기 차 기준 보기(`left`/`right`/`opposite`/`same`)를 쓴다. 블랙박스는 원래 내 차 기준으로 보이는 영상이라 **이 고정과 딱 맞는다.**
- 판정 엔진은 값 객체 `{"value", "source"}`를 읽고, 출처가 `user`인 값으로 적용된 가감 요소에만 "입증 필요"를 붙인다(`fault_engine._eval`, D6). 출처 `model`·`vehicle`은 그대로 지나간다. 그래서 영상 값을 넣으려고 판정 엔진을 고칠 필요가 없다.

**지금 코드가 그대로 맞지 않는 점**
- MTM 영상 사건(`POST /api/cases`)은 `source=blackbox`면 요청 안에서 바로 `unsupported`가 된다(현황 7.1). 모서리 단계도 블랙박스에는 뜻이 없다(현황 7.2). **이 영역은 MTM 것이라 고치지 않는다** → HMTM 영역에 새 흐름을 둔다 (3절).
- 화면 기준 값(`heading_start`, `approach_speed`, `intersection_entry_speed`, 영역 진입 `enter_zone`)은 카메라가 움직이는 블랙박스에서 뜻을 잃는다. 블랙박스 분석기는 이 값을 내지 않고 **진입 방위(`entry_from`)**로 좌우 관계를 준다 (1.3).

## 1. 블랙박스 분석기 빈자리

### 1.1 입력

| 입력 | 형식 | 필수 | 설명 |
|---|---|---|---|
| `video_path` | 서버 디스크의 파일 경로 | 예 | 올린 블랙박스 영상(앞 카메라 한 개). mp4 등 OpenCV가 읽는 형식 |
| `recorded_at` | `{"start_ms": int \| null, "source": "filename" \| "metadata" \| "app" \| "user" \| null, "tz": "Asia/Seoul"}` | 아니오 | 영상 첫 프레임의 촬영 시각 추정 (5절). 분석기는 **판정에 쓰지 않는다.** 화면 시각 표시(OSD)를 읽을 수 있는 분석기면 그 값을 출력 `clock`에 돌려줄 수 있다 |
| `work_dir` | 경로 | 예 | 중간 파일(`tracks.json`, `ego_motion.json` 등)을 쓸 사건 폴더 |
| `progress` | `callable(int 0~100)` \| None | 아니오 | 진행률 알림. 가짜 분석기는 무시해도 됨 |

- 차량 기록(samples)은 분석기에 **주지 않는다.** 분석기는 영상만 보고, 차량 기록과 합치는 일은 HMTM이 한다 (4절). 그래야 분석기를 바꿔도 합치는 규칙이 그대로다.
- **앞 카메라만 받는다 (확정 Q8).** 뒤 카메라(`_R` 파일 등)는 보류 항목이다 (9.2).
- **뒤에서 받힌 사고**는 앞 카메라에 상대가 보이지 않는다. 분석기는 충격 시각(`jolt_t`, `collision.t`)과 `collision.contact: rear`(추정) 정도만 내고 상대 항목은 비워 두며, 상대 종류·진행 방향·진입 방향(`same`)·앞뒤(`lead_order`)는 사용자 질문으로 받는다. 내 차 쪽 사실은 **차량 기록이 보강**한다: 충돌 때 서 있었음(`stationary_at_collision`, `movement_v0`의 "서 있었음" 조건), 진입 전 정지(`stopped_before_entry`), 사고 직전 브레이크·속도(정지 상태에서 충격을 받았는지). 차량 기록이 없으면 이 사실들도 질문으로 내려간다.

### 1.2 출력 개요

출력은 **FACTS 0.3 모양의 `facts`**에 블랙박스 전용 블록 몇 개를 더한 JSON 하나다 (확정 Q1) (`bb_facts.json`, `schema_version: "bb-0.2"`). 판정 엔진 변환기(`judge/adapter.py`)가 `facts` 부분을 그대로 읽을 수 있게 하는 것이 목표다.

- bb-0.1 → bb-0.2: 최상위 모양은 같고 `facts`에 항목이 늘었다(8.3.1~8.3.3). 새 항목은 모두 선택이라 bb-0.1 출력은 그대로 bb-0.2로도 맞다(키 없음 = 해 보지 않음). HMTM은 두 판을 모두 받는다.

```json
{
  "schema_version": "bb-0.2",
  "analyzer": {"name": "fake", "version": "0.1.0"},
  "status": "ok",
  "reason": null, "message": null,
  "video": {"duration_s": 30.0, "fps": 30.0, "frames": 900, "width": 1920, "height": 1080},
  "clock": {"osd_start_ms": null},
  "facts": { … FACTS 0.3 (1.3 표) … },
  "ego_motion": { … 시각 맞추기용 (1.3 F) … },
  "hints": { … 질문 참고 자료 (선택) … }
}
```

| 키 | 뜻 |
|---|---|
| `status` | `ok`(분석함) / `no_collision`(충돌을 못 찾음, `facts.collision.t`가 `null`) / `unsupported`(블랙박스 영상이 아님, 앞 유리 밖이 안 보임 등) / `failed`(읽기 실패 등). `ok`가 아니면 `reason`(코드), `message`(한국어 한 문장) |
| `facts` | FACTS 0.3 모양. 당사자 id는 **`ego`·`other` 고정** |
| `ego_motion` | 내 차 움직임의 시간 계열 요약. 차량 기록과 시각을 맞출 때만 씀 (판정에는 안 씀) |
| `hints` | 질문을 만들 때 붙일 참고 자료(예: 신호등 판독 기록 `light_hints`). HMTM이 질문 문구를 정하므로 분석기는 질문 문장을 만들지 않아도 됨 |

### 1.3 `facts`에 채울 항목

**값과 불확실성 표현 (모든 항목 공통)**

| 상태 | 표현 | HMTM이 하는 일 |
|---|---|---|
| 확실함 | `{"value": "left_turn", "source": "model", "confidence": 0.92, "evidence_frame": 412, "t": 13.73}` | 판정에 그대로 씀 (출처 `video`로 표시) |
| 추정만 있음 | `{"value": null, "source": "model", "guess": "left_turn", "confidence": 0.55, "evidence_frame": 412}` | 질문을 내고 `model_guess = guess`, `guess_source: "video"` |
| 봤지만 모름 | `{"value": null, "source": "model", "guess": null}` | 질문 (추정값 없음) |
| 해 보지 않음 | **키가 없음** | 질문이 필요하면 질문 (분석기가 아직 지원하지 않는 항목) |
| 해당 없음 | 키 없음 + 상위 조건으로 판단 (예: 교차로가 아니면 `junction_type` 없음) | 질문 조건이 안 맞아 안 물음 |

- `value`와 `guess`의 구분은 **분석기가 정한다.** "확실함"의 기준(정답률 몇 % 이상이면 `value`로 낼지)은 분석기마다 검증해서 정한다. 판정에 쓰는 값은 모르면 `null`이라는 원칙(CLAUDE.md "판단할 수 없는 값은 추측하지 말고 비워 둔다")을 그대로 따른다.
- `confidence`(0~1)는 선택이다. HMTM은 v0에서 `confidence`로 아무것도 정하지 않고 기록만 한다 (분석기마다 눈금이 달라서).
- `source`는 FACTS대로 **`model`**. HMTM 응답에서는 `video`로 보여 준다 (현황의 `modifiers[].source: "video"`와 같은 이름).
- 판정 엔진의 `unwrap`은 `value`·`source`·`evidence_frame`만 읽고 나머지 키(`guess`, `confidence`, `t`)는 무시하므로, 이 모양 그대로 판정 엔진에 넘겨도 된다.

**A. 충돌 (`facts.collision`)**

| 항목 | 값 | 필수 | 비고 |
|---|---|---|---|
| `collision.t`, `collision.frame` | 초, 프레임 (영상 처음 기준) | **필수** (`status: ok`일 때) | 충돌 순간. 차량 기록의 기준 시각 `T`가 됨 (5.4). 못 찾으면 `null`이고 `status: no_collision` |
| `collision.a`, `collision.b` | `"ego"`, `"other"` 고정 | **필수** | |
| `collision.zone` | `intersection` / `road` | 선택 | 충돌이 교차로 안인지. 없으면 HMTM이 "교차로 안이었나"를 물음 (지금 차량 사건은 `intersection`으로 고정, notes C13) |
| `collision.contact` | `front` / `left` / `right` / `rear` / `unknown` | 선택 | 내 차가 부딪힌 쪽. 추돌·측면 사고 구분 참고 |
| `collision.t_confidence` | 0~1 | 선택 | 충돌 시각의 믿음. 낮으면 차량 기록의 급감속으로 보강 (5.3) |

**B. 상대 (`facts.parties.other`)**

| 항목 | 값 | 필수 | 비고 |
|---|---|---|---|
| `cls` | `car` `truck` `bus` `two_wheeler` `bicycle` `person` | **필수** | FACTS 3-1. 판정 엔진이 이 값으로 사고 장(차대차·차대보행자·차대자전거)을 고른다. 이름·확신도 규칙은 8.3.1. 모르면 값 객체 `null` + `guess` |
| `movement` | `straight` `left_turn` `right_turn` `u_turn` `lane_change` `reverse` | **필수** | 상대가 **상대 기준으로** 어디로 가던 중인지 |
| `entry_from` | `west` / `east` / `north` / `south` | **필수** (교차로일 때) | **내 차 = `south` 고정** 규칙에 따른 방위. 내 차 기준 왼쪽 길 = `west`, 오른쪽 길 = `east`, 맞은편 = `north`, 같은 방향(앞·뒤) = `south` (차량 명세 2.6 방위 변환과 같은 표). 판정 엔진은 두 차 모두 `entry_from`이 있으면 화면 방향 벡터 대신 이 값으로 좌우를 판단함 |
| `intersection_entry` | `{"frame", "t"}` | 선택 | 상대가 교차로에 들어온 시각. 내 차 진입 시각과 함께 있으면 판정 엔진이 진입 차이(`entry_lead_sec`)를 계산 (명확한 선진입) |
| `signal_at_entry` | FACTS 3-5 값 | 선택 | 상대 쪽 신호는 블랙박스에 잘 안 보임. 대개 사용자 질문 |
| `turn_signal_used` | `true` / `false` | 선택 (2차) | 상대 지시등이 영상에 보이면 |
| `lead_order` | `leading` / `following` | 선택 | 같은 방향 사고에서 상대가 앞차인지 (추돌) |
| `lane_change_dir` | `left` / `right` | 선택 | 상대가 내 앞으로 끼어든 방향 |
| `stationary_at_collision` | `true` / `false` | 선택 | 상대가 서 있었는지 (차32 등) |

**C. 내 차 (`facts.parties.ego`)** — 차량 기록이 있으면 대부분 차량 기록이 이긴다 (4절). 영상 값은 차량 기록이 없을 때의 대신이자 시각 맞추기 검증용이다.

| 항목 | 값 | 필수 | 비고 |
|---|---|---|---|
| `cls` | | 아니오 | 내 차 종류는 앱 설정·차량 정보에서 옴. 분석기는 내지 않아도 됨 |
| `entry_from` | `south` 고정 | — | 분석기가 내지 않음. HMTM이 넣음 |
| `movement` | 위와 같음 | **필수** (추정이라도) | 화면 전체의 좌우 흐름(yaw)으로 좌·우회전·유턴 추정. 차량 기록은 후진만 확정하므로(차량 명세 4.3) 회전은 **영상이 주 근거**가 됨 |
| `intersection_entry` | `{"frame", "t"}` | 선택 | 내 차가 교차로에 들어간 시각 (정지선 통과). 있으면 차량 기록 서행 규칙의 "진입 1.5~3초 전 가정"(D5)을 실제 시각으로 바꿀 수 있음 (v0는 쓰지 않음, 확정 Q10) |
| `stationary_at_collision` | `true` / `false` | 선택 | 충돌 때 서 있었나 (배경 흐름 크기) |
| `stopped_before_entry` | `true` / `false` | 선택 | 진입 전 멈췄나 |
| `lane_change_dir` | `left` / `right` | 선택 | 진로 변경 방향 |
| `signal_at_entry` | FACTS 3-5 값 | 선택 | 내 차 앞 신호 색. 블랙박스에서 가장 잘 보이는 신호 |
| `lane_marking` | FACTS 3-7 값 | 선택 (2차) | 내 차로 바닥 화살표 (차량 사건에서는 영상 전용이라 뺐던 질문, notes C13) |
| `crossed_center_line`, `wide_turn` 등 | FACTS 3-2·3-10 | 선택 (2차) | 차선 인식이 되면 |

**D. 도로 (`facts.road`)**

| 항목 | 값 | 필수 | 비고 |
|---|---|---|---|
| `location` | `intersection` / `straight` / `parking_lot` / `roundabout` / `off_road` | **필수** (추정이라도) | 차량 사건의 `scene.place`에 해당 (지금은 어댑터 기본값 `intersection`, notes C3) |
| `junction_type` | `cross` / `t` | 선택 | 교차로일 때. 지금 기본값 `cross` |
| `signal_present` | `true` / `false` | 선택 | 신호등 유무. 지금 차량 사건은 꼭 답할 사용자 질문(notes E2) |
| `road_width` | `equal` / `different` + 당사자 `on_wider_road` | 선택 | 영상으로 판단하기 어려움. 대개 사용자 |
| `center_line` | `true` / `false` | 선택 | 중앙선 (차선 인식) |
| `night`, `low_visibility` | `true` / `false` | 선택 | 밝기·날씨 |

**E. 내지 않는 것 (블랙박스에서 뜻이 없음)**
- `heading_start`, `heading_before_collision`, `approach_speed`, `intersection_entry_speed`, `origin_zone`, `enter_road`, `events`의 `enter_zone`: 모두 **고정된 화면** 기준 값이다. 카메라가 움직이면 같은 화면 좌표가 프레임마다 다른 땅을 가리킨다(현황 7.2).
- 실제 속도 km/h(`speed_kmh`, `intersection_entry_speed_kmh`): 영상만으로는 단위를 모른다. 내 차 값은 차량 기록에서 온다. 단 **상대** 실속도를 실제로 잴 수 있는 분석기면 `parties.other.intersection_entry_speed_kmh`를 낼 수 있다 (8.3.3, 자전거 서행 위반). 화면 비율 속도를 km/h로 어림해 넣지는 않는다.

**G. 보행자·자전거 사고 항목 (bb-0.2)**
- 상대가 보행자(`person`)·자전거(`bicycle`)일 때 도표를 고르고 가감하는 데 쓰는 항목. `A_REQUESTS.md`에서 "채울 곳"이 영상·모델인 항목만 분석기 출력에 둔다. 목록·위치·값은 8.3.2(도표 선택용)·8.3.3(수정요소 전용).
- 횡단보도 거리는 판정 엔진 도표가 쓰는 **4구간**(위 / 10m 이내 / 10~30m / 30m 초과)으로 낸다 (8.3.2).

**F. `ego_motion` (시각 맞추기용)**

```json
"ego_motion": {
  "fps": 30.0,
  "step": 3,
  "t": [0.0, 0.1, 0.2],
  "speed_proxy": [0.0, 0.8, 1.1],
  "moving": [false, true, true],
  "jolt_t": [13.9],
  "yaw_proxy": [0.0, -0.4, -0.6]
}
```

- `speed_proxy`: 단위 없는 속도 대리 값 (MTM `ego_motion`의 `mag`). 차량 기록 `speedKmh`와 **모양**을 맞춰 시차를 찾는 데만 씀 (5.3).
- `jolt_t`: 충격 후보 시각(초). `collision.t`를 정하는 근거이자 차량 기록 급감속과 맞출 기준점.
- 간격은 0.1초 안팎이면 충분하다(차량 기록이 100ms).

### 1.4 인터페이스 위치와 교체 방법

**위치 (제안, HMTM 영역)**

```
backend/src/blackbox/
  analyzer.py      # 빈자리: BlackboxAnalyzer 규약, get_analyzer(), 출력 검사 validate_output()
  fake.py          # 가짜 분석기 (2절)
  scenarios/       # 가짜 분석기의 시나리오 JSON
  mtm.py           # (MTM 완성 뒤) 진짜 분석기 감싸기
  sync.py          # 영상 시각 ↔ 차량 기록 시각 (5절)
  merge.py         # user / vehicle / video / default 합치기 (4절)
  adapter.py       # 질문·판정 (src/vehicle/adapter.py 재사용)
  store.py, api.py # 저장·주소 (3절)
```

**규약**

```python
class BlackboxAnalyzer(Protocol):
    name: str
    version: str
    def analyze(self, video_path: str, recorded_at: dict | None, work_dir: str,
                progress: Callable[[int], None] | None = None) -> dict: ...   # 1.2 출력

def get_analyzer() -> BlackboxAnalyzer:
    """환경변수 HMTM_BB_ANALYZER: fake(기본) / mtm"""
```

- `analyze`는 예외를 내지 않고 `status`로 실패를 알린다 (`failed` + `reason`). 예외가 나면 HMTM이 `failed`, `server_error`로 바꾼다 (MTM 작업자와 같은 방식, 현황 3절 오류 처리).
- HMTM은 출력을 받은 뒤 `validate_output()`으로 모양을 검사한다(필수 항목, 값 범위, 당사자 id). 틀리면 `failed`, `analyzer_output_invalid`. 분석기를 바꿔도 이 검사가 계약 역할을 한다.

**교체 방법 (MTM 완성 뒤)**
1. MTM 블랙박스 분석 코드를 HMTM `backend/`로 가져온다. 가져오는 방식은 지금 MTM 코드와 같다(`docs/origin.md`: 커밋을 정해 `git archive`, `backend/src/analyze/` 등 MTM 영역은 직접 고치지 않음).
2. `src/blackbox/mtm.py`에 `BlackboxAnalyzer`를 구현한다. MTM 출력 모양이 1.2와 다르면 **여기서만** 바꾼다.
3. 계약 시험(`tests/test_blackbox_contract.py`, 2.3)을 진짜 분석기 + 짧은 샘플 영상으로 돌린다 (가중치·영상은 git 제외라 로컬에서만, CLAUDE.md).
4. 서버 `.env`에 `HMTM_BB_ANALYZER=mtm`. 나머지 코드(합치기·질문·판정·API)는 바꾸지 않는다.

### 1.5 MTM 블랙박스 실험 코드와 출력의 대응

세 모듈은 2026-11-05 MTM `feature/server`에서 추가된 실험 코드이고, HMTM에는 커밋 `32faa32`로 들어와 있다. 어디에도 연결되어 있지 않다 (현황 7.3). 옆 폴더의 MTM 저장소(`../MTM`)도 같은 커밋 `32faa32`라 그 뒤 진행은 이 문서에서 볼 수 없다 **(확인 필요: MTM 팀원의 지금 작업 범위)**.

| 실험 코드 | 지금 내는 것 | 대응하는 출력 (1.3) | 빈 곳 |
|---|---|---|---|
| `tools/blackbox_tracks.py` | 차량·이륜차(`models/bb_v1.pt`) + 사람·자전거·신호등(`yolov8s.pt`) 탐지·추적 → `tracks.json` | 모든 항목의 바탕 (상대 `cls`, 상자) | `bb_v1.pt`는 저장소에 없음 (git 제외) |
| `src/analyze/ego_motion.py` | 프레임별 `mag`(속도 대리), `tx`(좌우 흐름, yaw 대리), `ty`, `scale`, 달림·멈춤 구간, 충격 후보 프레임(`jolt_frames`, 3개까지), 좌우로 꺾은 총량(`yaw_total_px`) | **F `ego_motion` 전체**(`speed_proxy` ← `mag`, `yaw_proxy` ← `tx`, `jolt_t` ← `jolt_frames`). **A `collision.t` 후보**(첫 충격 후보). **C `ego.movement` 추정**(`yaw_total_px` 부호·크기 → 좌·우회전, 단 임계값 없음). **C `stationary_at_collision`·`stopped_before_entry`**(달림·멈춤 구간) | 기준값은 영상 12개를 눈으로 보고 정함, 정답 비교 없음. 회전 판정 임계값이 없음. 충격 후보가 "충돌"인지 "과속방지턱"인지 구분 못 함 |
| `src/analyze/lead_vehicle.py` | 앞차(화면 가운데에서 가장 가까운 차), 상자 너비, TTC, 충격 직전 앞차가 "코앞"(너비 35% 이상)인지 | **B `other` 고르기**(추돌이면 앞차가 상대). **B `lead_order: leading`**, `entry_from: south`(같은 방향). **A `collision` 확인**(충격 시각에 코앞이면 추돌일 가능성) | 앞차만 봄. 옆·맞은편에서 온 상대(교차로 사고의 대부분)는 다루지 않음. 영상 40개 눈 확인뿐 |
| `src/analyze/bb_signal.py` | 신호등 후보(탐지 5회·신뢰도 0.25 이상, 큰 순 3개), `light_cnn` 색 판독, 질문 두 개(`road.signal_present` 추정, `ego.signal_color` 추정 꺼 둠, `light_hints`) | **D `road.signal_present`**(후보가 있으면 `guess: true`). **C `ego.signal_at_entry`**(이름을 FACTS로 바꿈: `red` → `red`, `green` → `green`, `etc` → 값 없음(노랑·꺼짐·모름이 섞여 있어 하나로 못 정함)). `light_hints` → `hints` | 색 추정 정답률 30%(코드 주석, 커밋 메시지는 39%)라 `guess`도 꺼 둠 (`GUESS_COLOR = False`). 신호가 내 차 쪽 신호인지 구분 못 함 |

**아직 아무 실험도 없는 출력** (Q2 **대기**: MTM 팀원과 상의 중. 기본은 MTM이 영상 쪽 전부를 맡는 안이고, MTM 분석기가 내지 못하는 항목은 키를 비워 두면 HMTM이 **사용자 질문**으로 받는다(1.3 "해 보지 않음"). 그래서 상의 결과와 관계없이 HMTM 쪽 설계는 바뀌지 않는다)
- **B 상대 `movement`·`entry_from`**: 교차로 사고 판정에 가장 중요한 두 값. 상대 상자가 화면에서 어느 쪽에서 나타나 어디로 움직였는지 + 내 차 회전(yaw)을 빼는 보정이 필요하다.
- **D `road.location`·`junction_type`**: 교차로인지, 사거리·삼거리인지 (장면 분류).
- **C·B `intersection_entry`**: 정지선·교차로 경계 인식.
- **D `center_line`**, C `lane_marking`: 차선·노면표시 인식.

### 1.6 가중치 목록 `backend/models.json` (형식 `hmtm-models-1`, 2026-11-12)

진짜 분석기(`mtm`)가 쓰는 가중치는 git에 없고(재배포 금지) 각 PC의 `backend/models/`에 둔다. 어느 파일이 맞는지는 저장소의 `backend/models.json`이 정한다.

```json
{"schema": "hmtm-models-1",
 "models": {"detector":  {"role", "file": "bb_v3.pt", "version": "v8l_bb_v3", "sha256", "size_bytes", "source", "classes", "imgsz": 960, "conf": 0.15},
            "kind":      {…같은 칸…},
            "scene":     {…, "version": "scene_v1", "sha256": null, "size_bytes": null},
            "crosswalk": {…, "sha256": null}}}
```

| 칸 | 뜻 |
|---|---|
| `schema` | `"hmtm-models-1"`. 칸을 바꾸면 올린다 |
| `models` | 역할 네 개가 꼭 있음: `detector`(탐지·추적), `kind`(사고 직전 상대 종류 신호), `scene`(교차로 형태 M6), `crosswalk`(횡단보도 M5) |
| `file` | `backend/models/` 안 파일 이름. 실제로 읽는 경로는 `video_analyzer.py`의 환경변수·기본값(`HMTM_BB_DETECTOR` 등)이고, 검사는 그 경로의 파일을 이 항목과 대조한다 |
| `version` | 모델 이름(학습 판). `null`이면 아직 등록 안 됨 |
| `sha256`, `size_bytes` | 전달받은 파일의 sha256(16진수 64자)·바이트 수. 받기 전에는 둘 다 `null` |
| `source` | 누가 언제 어떻게 만든 파일인지 한 줄 |
| `classes`, `imgsz`, `conf` | 클래스 순서, 추론 크기·확신도 문턱(기록용. 실제 값은 아래 표의 코드·환경변수) |

**검사** (`src/blackbox/models.py`. `MtmAnalyzer`를 만들 때 = API 서버가 사건을 받을 때, 작업자가 켜질 때·분석할 때)

| 상태 | 조건 | 분석기 |
|---|---|---|
| `ok` | `version`·`sha256`이 있고 파일의 크기·sha256이 같음 | 씀 |
| `missing` | 등록됐는데 파일이 없음 | **준비 안 됨** (`POST`는 `503 analyzer_not_ready`, 분석 중이면 `failed / analyzer_not_ready`) |
| `mismatch` | 크기나 sha256이 다름 | **준비 안 됨** (목록과 다른 가중치로 결과를 내지 않음) |
| `unregistered` | `version`이나 `sha256`이 `null` (지금 `scene`, `crosswalk`) | 그 모델을 쓰는 단계만 건너뜀: 분석 동안 그 경로를 없는 파일로 바꿔 `bb_scene`·`bb_crosswalk`가 `model_missing`으로 넘어가게 함. 파일이 있어도 쓰지 않음 |

- 탐지(`detector`)는 `ok`여야 한다. sha256은 (경로, 크기, 수정 시각)이 같으면 다시 계산하지 않는다.
- `HMTM_BB_MODEL_CHECK=0`이면 검사를 끈다 (A가 목록에 없는 가중치로 실험할 때만. 서버에서는 켬).
- 새 가중치를 받으면 파일을 `backend/models/`에 두고 `version`·`sha256`·`size_bytes`·`source`를 채운다 (`tests/test_models_json.py`가 로컬 파일과 대조).

**추론 설정** (2026-11-12 코드 기준. 값을 바꾸면 이 표와 `models.json`의 `imgsz`·`conf`를 같이 고친다)

| 단계 | 모델 | 크기 | 확신도 문턱 | 보는 장면 | 정하는 곳 |
|---|---|---|---|---|---|
| 탐지·추적 (`track_video`) | `detector` | 960 | 0.15 | 영상 전체 | `HMTM_BB_IMGSZ`·`HMTM_BB_CONF` (기본 960·0.15). CPU 서버에서 느리면 640으로 낮춤 |
| 상대 종류 신호 (`bb_kind`) | `kind` | 960 | 0.15 (탐지), 신호로 셀 상자는 0.4 이상(`MIN_CONF`) | 사고 직전 2초(30프레임, 3프레임마다) + 뒤 3프레임 | `HMTM_BB_KIND_IMGSZ`·`HMTM_BB_KIND_CONF` (기본 960·0.15). `bb_kind.py` 자체 기본값은 640·0.1 (A 확인 항목) |
| 횡단보도 (`bb_crosswalk`, M5) | `crosswalk` | 960 | 요청 0.15. 지금 코드는 `conf`를 넘기지 않아 YOLO 기본값 0.25 (A 확인 항목) | 사고 앞뒤 구간(`CW_WINDOW`)에서 보행자 발 위치가 있는 장면 | `scene_crosswalk.relate_crosswalk(imgsz=960)` |
| 교차로 형태 (`bb_scene`, M6) | `scene` | 384 | — (분류) | 요청은 충돌 직전 5장면 평균. 지금 코드는 충돌 3초 전~충돌 순간을 0.5초 간격으로 뽑은 장면(최대 7장)의 클래스 확률 평균 (A 확인 항목) | `scene_crosswalk.classify_scene` (`SCENE_WINDOW`, `SCENE_STEP`) |

- 요청된 설정과 지금 코드가 다른 곳은 `docs/analyzer-integration-notes.md` 5절에 A의 확인 항목으로 적었다. 분석 엔진 코드는 A 영역이라 HMTM이 고치지 않는다.

## 2. 가짜 분석기

### 2.1 방식

- `fake.py`의 `FakeAnalyzer.analyze()`는 영상 내용을 보지 않고 **시나리오 JSON 하나를 골라 그대로 돌려준다.** 단 `video`(길이·fps·크기)는 영상 파일에서 실제로 읽어 시나리오 값을 덮는다 (OpenCV `CAP_PROP_*`. 읽지 못하면 시나리오 값). 그래야 시각 맞추기(5절)를 실제 영상 길이로 시험할 수 있다.
- **시나리오 고르는 법** (위에서부터 처음 맞는 것, 확정 Q16):
  1. 요청의 `scenario` 칸 (가짜 분석기일 때만 받음. 진짜 분석기에서는 무시)
  2. 영상 파일 이름에 `__scn-<이름>`이 들어 있으면 그 시나리오 (예: `20261109_143012_F__scn-right_turn_left_straight.mp4`)
  3. 기본 시나리오 `HMTM_BB_FAKE_DEFAULT` (없으면 `right_turn_left_straight`)
- **지연 흉내**: 시나리오의 `fake.delay_sec`만큼 기다리며 `progress`를 0→100으로 올린다 (앱의 "분석 중" 화면 시험용, 기본 0).
- 시나리오 파일은 1.2 출력 전체 + `fake` 블록(`delay_sec`, `description`, `expect`)이다. `expect`는 예상 판정(도표·비율)으로, 테스트에서 확인한다.

```json
{
  "schema_version": "bb-0.2",
  "fake": {"description": "내 차 우회전, 상대가 왼쪽 길에서 직진, 비신호 사거리", "delay_sec": 0,
           "expect": {"rule_id": "차13-1", "fault_by_party": {"ego": 60, "other": 40}}},
  "status": "ok",
  "video": {"duration_s": 30.0, "fps": 30.0, "frames": 900, "width": 1920, "height": 1080},
  "facts": {
    "schema_version": "0.3",
    "collision": {"a": "ego", "b": "other", "t": 18.2, "frame": 546, "zone": "intersection"},
    "parties": {
      "ego":   {"movement": {"value": "right_turn", "source": "model", "confidence": 0.9}},
      "other": {"cls": {"value": "car", "source": "model"},
                "movement": {"value": "straight", "source": "model"},
                "entry_from": {"value": "west", "source": "model"}}
    },
    "road": {"location": {"value": "intersection", "source": "model"},
             "junction_type": {"value": "cross", "source": "model"},
             "signal_present": {"value": null, "source": "model", "guess": false}}
  },
  "ego_motion": {"fps": 30.0, "step": 3, "t": [], "speed_proxy": [], "jolt_t": [18.2]}
}
```

### 2.2 시나리오 목록 (제안)

`expect`의 도표·비율은 구현할 때 판정 엔진으로 돌려 확인하고 적는다. 아래 "예상"은 차량 사건 확인 결과(devlog 2026-11-09)와 도표 이름으로 짐작한 것이다.

| 이름 | 내용 | 시험하는 것 | 예상 |
|---|---|---|---|
| `right_turn_left_straight` | 내 차 우회전, 상대 왼쪽 길 직진, 비신호 사거리, 신호 유무만 `guess` | 기본 흐름, 남은 질문(신호 유무) | `차13-1` 60:40 (도로 폭 `equal`) |
| `straight_same_time` | 둘 다 직진, 상대 오른쪽 길, 진입 시각 둘 다 있음 (차이 0.3초) | 진입 시각 → `entry_lead_sec`, 차량 기록 서행과 합치기 | `차12-1` 계열 |
| `left_turn_opposite` | 내 차 좌회전, 상대 맞은편 직진, 신호 있음, 내 차 신호 `green` | 신호 교차로, 영상 신호 색 | 신호 교차로 도표 (구현 때 확인) |
| `rear_end_lead` | 상대가 앞차(`lead_order: leading`, `entry_from: south`), 상대 서 있음, 장소 `straight` | 같은 방향 사고, `lead_vehicle` 대응 | 추돌 도표 (구현 때 확인) |
| `ego_reverse_video_wrong` | 영상은 내 차 `straight` 추정, 차량 기록은 기어 R | 출처 충돌(4.3): 차량 기록이 이기고 충돌 기록 | 진행 방향 `reverse`(출처 `vehicle`) |
| `mostly_unknown` | 충돌 시각만 있고 나머지는 거의 `guess` 또는 `null` | 질문이 많은 경우, `provisional` | `needs_answers` |
| `no_collision` | `status: no_collision` | 충돌 못 찾음 → 사용자가 충돌 시각 고르기 (3.3). 고른 뒤에도 다시 `no_collision` (`last_pick`) | `no_collision` |
| `no_collision_pick` (2026-11-12) | `status: no_collision`, 후보 2개(`hints.collision_candidates`), `fake.on_pick: right_turn_left_straight` | `PUT collision` 처음부터 끝까지: 고르면 그 순간으로 다시 분석·판정, 영상 삭제 | `no_collision` → 고르면 `차13-1` 60:40 |
| `unsupported` | `status: unsupported`, `reason: not_blackbox` | 고정 카메라·실내 영상 등 | `unsupported` |
| `analyzer_broken` | 필수 항목 빠짐 | `validate_output` → `failed` | `failed` |
| `ped_crosswalk_unsignalized` (2.4) | 상대 보행자(`person`)가 신호 없는 횡단보도 위에서 건넘, 내 차 직진 | 차대보행자 장 고르기, 횡단보도 항목 | `보13` 100:0, 가감 요소 질문 3개 남음 (`needs_answers`, 2026-11-11 전에는 `done`). 밤이라고 답하면 85:15 — 엔진 확인 |
| `bike_crossing_side` (2.4) | 상대 자전거(`bicycle`)가 왼쪽에서 자전거횡단도로 건넘, 내 차 직진 | 차대자전거 장 고르기, 자전거 항목 | `거42-1` 100:0, 남은 질문 `road.center_line` — 엔진 확인 |

### 2.3 테스트·데모에서 쓰는 법

| 쓰임 | 방법 |
|---|---|
| 단위 시험 | `FakeAnalyzer().analyze(path, None, tmp, scenario=...)`를 바로 부르고 `merge`·`adapter`를 시험. 영상 파일은 몇 프레임짜리 작은 mp4를 테스트 안에서 만들거나(OpenCV `VideoWriter`), 길이를 못 읽어도 되는 시험이면 빈 파일 |
| API 시험 | `TestClient`로 `POST /api/bb-cases`에 작은 파일 + `scenario` 칸. 지연 0이라 응답 뒤 바로 `GET`하면 결과가 있음 (3.2) |
| 계약 시험 | `tests/test_blackbox_contract.py`: 모든 시나리오가 `validate_output`을 통과하는지, 시나리오 `facts`를 판정 엔진 변환기(`judge/adapter.to_engine_facts`)가 오류 없이 읽는지, `expect`와 판정이 같은지. 진짜 분석기로 바꾼 뒤에는 같은 시험을 진짜 출력에 돌림 |
| 앱 데모 | 서버 `HMTM_BB_ANALYZER=fake`. 앱의 개발자 메뉴에서 시나리오를 고르면 업로드 요청에 `scenario`를 붙임. 아무 영상이나 올려도 됨 (영상 길이는 진짜로 읽으므로 차량 기록 첨부까지 실제처럼 돎) |
| 실차 데모 | 실제 블랙박스 영상 + 실제 루프 CSV + 그 사고에 맞춘 시나리오 하나를 손으로 써서 올림. 영상 분석만 가짜이고 시각 맞추기·차량 규칙은 진짜로 돎 |

### 2.4 보행자·자전거 시나리오 계획 (bb-0.2, 다음 작업)

> 이 절은 계획이었고 2026-11-10 `feature/bb-ped-bike`에서 구현했다 (순서 6 앱 시나리오 목록은 앱이 `bb.scenario`를 글자 그대로 넘겨 고칠 것이 없음). 충돌 시각은 다른 시나리오와 같은 18.2초로 했다. 구현에서 달라진 점은 `docs/bb-ped-bike-notes.md`.

**시나리오 두 개**

| 이름 | `facts`에 넣을 값 (모두 `source: "model"`) | 남길 질문 | `expect` (구현 때 판정 엔진으로 확인) |
|---|---|---|---|
| `ped_crosswalk_unsignalized` | `other.cls = person` (`confidence` 0.9), `other.ped_place = crosswalk`, `road.crosswalk_signal = false`, `road.location = straight`, `ego.movement = straight`, `other.movement`·`entry_from`은 넣지 않음(보행자는 진행 방향 도표가 아님), `collision.zone = road`, `collision.contact = front` | 없음이 목표. 보13은 `crosswalk_signal`·`ped_place`·내 차 진행 방향만 읽음 | `보13`, `{"ego": 100, "other": 0}`, 장 `car_pedestrian` |
| `bike_crossing_side` | `other.cls = bicycle` (`confidence` 0.85), `other.on_bike_crossing = true`, `other.entry_from = west`, `other.movement = straight`, `ego.movement = straight`, `road.location = straight` | 자전거 쪽 남은 질문(`bike_lane_type` 등)이 있으면 그대로 둠 | `거42-1`, `{"ego": 100, "other": 0}`, 장 `car_bicycle`. `crossing_road`를 비우면 거41-1·거33-2가 판단 보류로 남는지, 거42-1만 고르는지 확인 |

- 두 시나리오 모두 `schema_version: "bb-0.2"`. 거리 4구간(8.3.2)은 이 두 개로 시험하지 않는다. 필요하면 `ped_near_crosswalk_20m`(10~30m, 수정요소 `ped_near_10_30m`) 같은 시나리오를 나중에 더한다.

**같이 할 일 (다음 작업 범위)**

| 순서 | 할 일 | 파일 |
|---|---|---|
| 1 | `SCHEMA_VERSION`을 `bb-0.2`로, bb-0.1 출력도 받게. 검사표(`PARTY_VALUES`, `ROAD_VALUES`)에 8.3.2·8.3.3의 값 목록 추가. `dist_from_crosswalk_m`은 0 이상 숫자, `bin`은 4구간 이름 | `src/blackbox/analyzer.py` |
| 2 | 분석기 `facts`의 보행자·자전거 항목이 판정 facts 껍데기(`_shell`)까지 넘어가는지 확인. 지금 `_shell`은 정해 둔 키와 `merge.video_values`가 넘기는 값만 담음 | `src/blackbox/adapter.py`, `merge.py` |
| 3 | 상대 `cls`가 `person`·`bicycle`이면 질문도 그 장으로 (A_REQUESTS 요청 3: `chapters.CHAPTER_OF`에 `person` 추가는 MTM 영역이라 HMTM에서 바꿀지 따로 정함. 블랙박스 쪽에서 장을 넘기는 방법 포함) | `src/blackbox/adapter.py` (필요하면 `src/app/chapters.py` 최소 수정 + `docs/origin.md`) |
| 4 | `cls`가 `guess`뿐일 때 "상대 종류" 질문을 맨 앞에 두고, 답이 오면 장을 다시 고름 (8.3.1) | `src/blackbox/adapter.py` |
| 5 | 시나리오 두 파일 + 계약 시험(`validate_output`, `to_engine_facts`, `expect`) | `src/blackbox/scenarios/`, `tests/test_blackbox_contract.py` |
| 6 | 앱 개발자 메뉴의 시나리오 목록, `local.properties`의 `bb.scenario` 예 | `android/` |

## 3. 블랙박스 사건 흐름

### 3.1 전제

- MTM 영역(`backend/src/app/`, `src/analyze/`, `src/server/`, `judge/`)은 고치지 않는다 (차량 명세 8.1). 기존 `/api/cases`와 MTM 작업자(`worker.py`, `jobs` 표)도 그대로 둔다.
- 새 흐름은 HMTM 영역(`backend/src/blackbox/`)에 두고, `app.py`에는 지금처럼 `install` 한 줄만 더한다 (차량 명세 8.3과 같은 방식).

### 3.2 주소 (확정 Q5)

| 메서드 | 경로 | 하는 일 | 응답 |
|---|---|---|---|
| POST | `/api/bb-cases` | `multipart/form-data`: `video`(파일, 필수), `meta`(JSON 문자열: 파일 이름, 촬영 시각 추정 `recorded_at`, 영상 길이), `vehicle`(JSON 문자열, 선택: 차량 명세 2.1의 `range`·`samples`·`vehicle`·`client`, `t_event`는 없음), `scenario`(가짜 분석기일 때만) | `202` 블랙박스 사건 (`status: analyzing`) |
| GET | `/api/bb-cases/{id}` | 상태와 결과. 분석 중이면 `progress` | `200` |
| PUT | `/api/bb-cases/{id}/vehicle` | 차량 기록을 나중에 붙이거나 바꿈 (업로드 때 못 붙였을 때, 시각을 고쳤을 때) | `200` (분석이 끝났으면 바로 다시 합침) |
| PUT | `/api/bb-cases/{id}/sync` | 사용자가 시각 맞추기를 고침 (예: "영상의 이 장면 = 차량 기록의 이 시각", 5.3) | `200` |
| PUT | `/api/bb-cases/{id}/answers` | 지금까지의 답 전부 (차량 명세 2.2와 같은 규칙: 통째로 바꿈, 키 모양 검사, 바로 422) | `200` **(구현, 3.6)** |
| PUT | `/api/bb-cases/{id}/collision` | 사고 순간이 없거나 불확실할 때(`collision_review.needed`) 사용자가 사고 순간(영상 안 초)을 고름 → 그 순간으로 분석기를 다시 돌림 | `202` 분석 중 **(구현 2026-11-12, 3.6)** |
| DELETE | `/api/bb-cases/{id}` | 사건 전부 삭제: 차량 기록·`bb_facts`·답·결과, 사건 폴더 (분석 중이라 영상이 아직 있거나 `HMTM_KEEP_VIDEO=1`로 보관 중이면 영상도) | `204` **(구현, 3.6)** |

- 상태: `analyzing` → `needs_answers` / `done` / `no_collision` / `unsupported` / `failed`. 영상 사건(현황 2.1)과 같은 이름을 쓴다. `waiting_scene`(모서리)은 없다.
- 영상 분석이 끝난 뒤의 일(시각 맞추기, 차량 규칙, 질문, 판정)은 **요청 안에서 바로** 한다 (차량 사건과 같음, 1초 안쪽). 오래 걸리는 것은 영상 분석뿐이다.
- 오류 모양·인증·404 규칙은 차량 사건과 같다 (`bb_case_not_found`, 확정 Q5).
- **원본 영상은 분석이 끝나면 지운다 (확정 Q13).** 분석 결과가 어느 상태로 끝나든(`ok`·`no_collision`·`unsupported`·`failed`) 영상 파일을 지우고 `bb_facts.json`과 판정 관련 값만 남긴다. 개발 모드에서만 환경변수 `HMTM_KEEP_VIDEO=1`이면 영상을 남긴다(분석기 시험·재분석용). 영상 뒤의 일(시각 맞추기, 차량 규칙, 질문, 판정, `PUT` 4개)은 모두 `bb_facts`(`facts`·`ego_motion`)만으로 하므로 영상이 없어도 된다.
- **Q13의 예외: 사고 순간 고르기 (2026-11-12).** 분석기가 사고 순간을 못 찾았거나(`no_collision`) 불확실하면(`collision_review.needed`: 추정·확신도 낮음) 원본 영상을 **사용자가 사고 순간을 고를 때까지, 최대 7일** 둔다.
  이유: 사고 순간은 상대 고르기·상대 종류·장면·시각 맞추기가 모두 기대는 값이라 `bb_facts`만으로는 다른 순간으로 다시 계산할 수 없고, 분석기를 그 순간으로 **다시 돌려야** 한다(영상이 있어야 함). 사고 순간이 없으면 판정 자체가 없어서, 영상을 지우면 사용자가 할 수 있는 일이 영상을 다시 올리는 것뿐이다.
  고른 순간으로 판정이 되면 그때 지운다(`HMTM_KEEP_VIDEO=1`이면 보관). 7일 안에 고르지 않으면 API 프로세스가 영상을 지운다(1시간마다 확인, `HMTM_BB_EXPIRE_SEC`). 기한은 처음 분석이 끝난 때부터이고 다시 골라도 늘지 않는다. 7일은 영상 사건(`MTM_KEEP_DAYS` 기본 7일)과 같게 둔 값이다.
- 영상을 지우므로 **분석기를 바꿔도 지난 사건은 다시 분석할 수 없다.** 그래서 `bb_facts.analyzer`(이름·판)를 사건에 함께 남겨 어느 분석기의 결과인지 설명할 수 있게 한다. 앱의 근거 화면은 앱 기기에 있는 원본 영상을 쓴다(서버는 영상을 내주지 않음, 기존 영상 사건의 `/evidence`와 같은 방식).

### 3.3 처리 순서

```
POST /api/bb-cases ─▶ 영상 저장(data/bb_cases/<id>/video.*), 행 생성(status=analyzing)
                      vehicle 칸이 있으면 samples.validate로 바로 검사 (틀리면 422, 사건을 만들지 않음)
                      분석 작업을 HMTM 작업 줄에 넣음 (3.4)
[분석 작업]           get_analyzer().analyze() → validate_output → bb_facts.json 저장
                      영상 파일 삭제 (HMTM_KEEP_VIDEO=1이 아니면, 확정 Q13). 사고 순간 확인이 필요하면 7일 보관 (Q13 예외)
                      status가 ok가 아니면 그 상태로 끝 (no_collision이면 PUT collision을 기다림)
PUT collision ──────▶ 고른 순간을 남기고 status=analyzing → 위 [분석 작업]을 collision_t로 다시 (판정되면 영상 삭제)
                      ok면 아래 "합치기"를 돌리고 status = needs_answers / done
[합치기] (분석 직후, PUT vehicle·sync·answers·collision 때마다 처음부터 다시)
  1. 시각 맞추기 (5절): recorded_at + 차량 기록 → offset, 신뢰도
  2. 차량 규칙: T = 영상 시작 + offset + collision.t → rules.run_rules (Ctx는 manual, 5.4)
  3. 합치기 (4절): user > vehicle > video > default, 충돌 기록
  4. 질문: 영상·차량으로 못 정한 것만 (adapter.base_questions + situation.questions)
  5. 판정: judge_bridge.judge (차량 사건 어댑터와 같은 껍데기)
GET ◀─ 블랙박스 사건 (차량 사건 객체 2.5 + 영상·시각 맞추기 칸)
```

### 3.4 오래 걸리는 분석을 어디서 돌리나

| 안 | 내용 | 장단 |
|---|---|---|
| (가) API 프로세스 안 백그라운드 스레드 **(확정 Q6, `fake`)** | `POST`가 행을 만들고 스레드 하나(동시에 1개)에 분석을 넘김. 서버를 껐다 켜면 `analyzing`으로 남은 사건을 다시 넣음 | 가짜 분석기는 바로 끝나서 충분함. MTM 작업자를 안 건드림. YOLO를 API 프로세스에서 돌리면 요청이 느려질 수 있음 |
| (나) HMTM 전용 작업자 프로세스 **(확정 Q6, `mtm`, 2026-11-12 구현)** | `src/blackbox/worker.py`. 따로 작업 표를 두지 않고 `bb_cases.status = analyzing`이 작업 줄 | 진짜 분석기에 맞음. 작업자를 따로 띄워야 함 (Windows 명령은 CLAUDE.md, `tools/serve.sh`(MTM)는 고치지 않음) |
| (다) MTM 작업자에 작업 종류 추가 | `jobs.kind = bb_analyze` | **MTM 영역 수정**이라 제외 |

- `HMTM_BB_ANALYZER=fake`(기본)는 (가), `mtm`은 (나) (확정 Q6). `mtm`이면 API 프로세스는 `POST`에서 행과 영상만 만들고 분석 스레드를 띄우지 않으며, 켤 때 `resume`도 하지 않는다.
- 작업자: `python -m src.blackbox.worker` (API 서버와 같은 환경변수, 같은 `backend/` 폴더). 1초마다 `analyzing` 사건을 **오래된 것부터 하나** 꺼내 `api.analyze_case`(가와 같은 함수)로 분석한다. `--once`면 남은 사건을 다 하고 끝낸다.
- **한 작업자 프로세스에서 분석은 한 번에 하나.** `video_analyzer.py`가 `track_video`의 모듈 전역(`MODEL`·`IMGSZ`·`CONF`)을 분석 동안만 바꿔치기하므로, 같은 프로세스 안에서 두 분석이 겹치면 한 사건이 다른 사건의 설정으로 탐지될 수 있다. 작업자 루프는 스레드 하나로 차례로 돌고, `MtmAnalyzer.analyze`도 잠금(`_MTM_RUN`)으로 막는다 (다른 곳에서 불러도 겹치지 않음). 빨리 하려면 프로세스를 늘려야 하는데, 지금은 같은 사건을 두 작업자가 가져가는 것을 막는 장치가 없어 **작업자는 하나만** 띄운다.
- 서버·작업자를 다시 켤 때: 작업자가 `analyzing`으로 남은 사건(분석 도중 꺼진 것 포함)부터 다시 분석한다. 영상은 분석이 끝나야 지우므로(Q13) 남아 있다.
- 분석 중 삭제(`DELETE`): API가 행과 사건 폴더를 지우면 작업자는 진행률 알림에서 행이 없는 것을 보고 멈추고, 분석기가 쓰던 파일까지 사건 폴더를 다시 지운다.
- 작업자를 띄우지 않으면 사건이 `analyzing`에 머문다 (앱은 10분 뒤 `analysis_timeout`). 작업자는 켤 때 가중치 검사 결과(1.6)를 로그에 남긴다.

### 3.5 지금 코드에서 다시 쓰는 것

| 지금 코드 | 블랙박스 흐름에서 | 바꿀 점 |
|---|---|---|
| `vehicle/samples.py` (`validate`, `Timeline`, `signal_intervals`, `VehicleError`) | **그대로.** 첨부한 차량 기록 검사·읽기 | 블랙박스 사건은 `t_event`를 영상에서 정하므로, 업로드 때는 `t_event` 없이 검사하는 함수가 필요 (`validate`를 나눔). 블랙박스 사건은 구간 제한을 `영상 길이 + 30초`, 최대 300초로 둠 (5.5, 확정 Q12). 차량 사건(`/api/vehicle-cases`)의 120초는 그대로 |
| `vehicle/rules.py` (`run_rules`, 규칙 5개, `auto_answer`) | **그대로.** `Ctx(T, "manual")` | 규칙 코드는 바꾸지 않음. v0는 지금 `slowed_v0`(진입 1.5~3초 전 가정) 그대로. 영상의 내 차 진입 시각을 쓰는 `slowed_v1`은 진짜 분석기가 그 값을 낼 때 만듦 (확정 Q10) |
| `vehicle/adapter.py` | **대부분 재사용**: `to_mtm`(방위 변환), `clean_question`, 질문 문구 바꾸기(`NAMES`), `_met`, `view_result`, `judge`, `data_quality`, 답 키 모양(`ANSWER_KEY`) | `shell()`(facts 껍데기)을 "분석기 `facts` 위에 차량 값을 얹는" 함수로 바꿈. `base_questions()`는 영상이 정한 항목을 빼고 `guess_source: "video"`를 붙이게 바꿈. `build()`는 합치기(4절)를 받게 나눔. **v0는 `src/blackbox/`가 `src/vehicle/`을 불러 씀. 둘 다 쓰는 코드가 커지면 `src/hmtm_core/`(가칭)로 옮김 (확정 Q4)** |
| `vehicle/store.py` | 같은 방식(기존 DB 파일, `CREATE TABLE IF NOT EXISTS`, 행 하나) | 표 `bb_cases`. 영상은 분석 동안만 사건 폴더 `data/bb_cases/<id>/`에 두고 분석이 끝나면 지움 (Q13). 사건 삭제 때 폴더도 지움 |
| `vehicle/api.py` (`me`, `own_case`, `json_body`, 오류 처리기, `delete_on_withdraw`) | 인증·오류 모양·탈퇴 미들웨어 재사용 | 탈퇴 미들웨어가 `bb_cases`도 지우게 (`delete_owner` 둘 다 부름) |
| `vehicle/api.py`의 `install(app)` | `blackbox/api.py`에도 `install` | `app.py`에 한 줄 더 (MTM 영역 한 줄 추가. 차량 사건 때와 같은 예외) |
| MTM `situation.questions`, `answers.check`·`remaining`·`fill_guesses`·`to_assumptions`, `judge_bridge.judge` | **그대로** (차량 명세 8.4에서 같은 껍데기로 동작 확인) | 분석기 `facts`가 들어오면 질문이 영상 사건에 더 가까워짐. 영상 전용으로 뺐던 질문(`lane_marking`)을 다시 낼지 |

### 3.6 bb-cases API 최종 요청·응답 형식 (2026-11-09, 흐름 2부)

> 앱 2부(질문 화면·지난 분석·삭제)는 이 절을 보고 만든다. 구현: `backend/src/blackbox/api.py`, 설계와 다르게 한 점: `docs/bb-flow-notes.md`.
> 모든 주소는 `Authorization: Bearer <access>`(가입까지 끝난 회원). 남의 사건·없는 사건은 `404 bb_case_not_found`.
> 오류 모양은 차량 사건과 같다: `{"error": "<코드>", "message": "<한국어 한 문장>"}`.

**지금 있는 주소**

| 메서드 | 경로 | 요청 | 성공 응답 |
|---|---|---|---|
| POST | `/api/bb-cases` | `multipart/form-data` (아래) | `202` 분석 중 객체 |
| GET | `/api/bb-cases` | `?before=<created_at ms>&limit=20` | `200` 내 사건 목록 (아래) |
| GET | `/api/bb-cases/{id}` | — | `200` 분석 중 객체 / 끝난 사건 객체 |
| PUT | `/api/bb-cases/{id}/answers` | JSON `{"answers": {질문 키: 값}}` | `200` 끝난 사건 객체 |
| PUT | `/api/bb-cases/{id}/collision` | JSON `{"t": 영상 안 초}` | `202` 분석 중 객체 (2026-11-12, 아래) |
| DELETE | `/api/bb-cases/{id}` | — | `204` (본문 없음) |
| DELETE | `/api/bb-cases` | — | `200` `{"deleted": 개수}` 내 사건 전부 (앱 "모든 기록 삭제", 2026-11-10) |

> **2026-11-10 설계 변경 (4.4)**: 차량 기록은 판정에 바로 넣지 않는 참고 자료다. `result`는 영상·사용자 답·기본값으로 낸 판정이고,
> 차량 기록을 더한 판정은 `result_with_vehicle`, 차이를 만든 기록은 `vehicle_effects`, 그래프용 요약은 `vehicle_timeline`.
> 아래 표에서 "(4.4)"가 붙은 칸이 새로 생기거나 뜻이 바뀐 칸이다.

아직 없는 주소(3.2 표): `PUT …/vehicle`, `PUT …/sync`. `PUT …/collision`은 2026-11-12에 더했다 (아래). 사건 목록 `GET /api/bb-cases`는 2026-11-10에 더했다 (아래).

#### POST `/api/bb-cases`

| 칸 | 형식 | 필수 | 내용 |
|---|---|---|---|
| `video` | 파일 | 예 | 앞 카메라 영상 하나. 최대 `MTM_MAX_UPLOAD_MB`(기본 200MB) |
| `meta` | JSON 문자열 | 아니오 | `{"filename", "recorded_at": [{"source": "filename"\|"metadata"\|"user", "start_ms"}], "duration_s", "mtime_ms", "tz_offset_min", "size_bytes"}`. 수정 시각은 `recorded_at`이 아니라 `mtime_ms`로만 (모르는 출처는 `app`으로 받음) |
| `vehicle` | JSON 문자열 | 아니오 | 차량 명세 2.1에서 `t_event`를 뺀 것: `{"range": {"from", "to"}, "samples": [...], "vehicle": {"cls"}, "client": {...}, "location": null}`. 구간 최대 300초 |
| `scenario` | 문자열 | 아니오 | 가짜 분석기 시나리오 이름 (진짜 분석기에서는 무시) |

- 응답 `202`: `{"id", "status": "analyzing", "progress": 0, "created_at", "updated_at"}` (시각은 epoch ms).
- 오류: `422 request_invalid`(meta·vehicle이 JSON 객체가 아님), `422 range_invalid` / `samples_empty` / `samples_too_many` / `samples_unsorted` / `sample_invalid` 등(차량 기록 검사, 차량 사건과 같은 코드), `422 location_unsupported`, `422 scenario_unknown`, `422 video_empty`, `413 video_too_large`, `503 analyzer_not_ready`. 오류면 사건을 만들지 않는다.

#### GET `/api/bb-cases` (사건 목록, 2026-11-10)

- 내 사건만, **최근 것부터**(`created_at` 내림차순). `limit` 기본 20, 최대 50. 다음 쪽은 마지막 항목의 `created_at`을 `before`로 (`/api/posts`와 같은 방식). 빈 목록은 `[]`.
- 응답: 배열. 한 줄 = `{"id", "status", "progress", "created_at", "updated_at", "filename", "recorded_at_ms", "collision_t", "other_cls": {"value", "label", "source"} | null, "chapter", "rule_id", "title", "fault_by_party", "fault_display", "provisional", "remaining_count", "reason", "vehicle_record", "sync_grade", "fault_display_with_vehicle", "vehicle_changes"}`.
  - (2026-11-12) `collision_review_needed`: 사고 순간 확인이 필요한지 (`collision_review.needed`). `collision_pick_until`: 사고 순간을 고를 수 있는 기한(epoch ms, `collision_review.pick_until`, 없으면 `null`).
  - (4.4) `vehicle_record`: 차량 기록을 붙였는지 (끝난 사건은 `data_quality.vehicle_record`), `sync_grade`: 시각 맞추기 등급, `fault_display_with_vehicle`: `result_with_vehicle.fault_display`(기록이 없으면 `null`), `vehicle_changes`: 결과를 바꾼 기록(`vehicle_effects` 중 `applied: true`)이 있는지.
  - 분석 중이면 `progress`만 의미 있고 판정 칸은 `null`. `no_collision`·`unsupported`·`failed`면 `reason`(분석 코드), 판정 칸 `null`.
  - `recorded_at_ms` = 시각 맞추기의 촬영 시작 시각(`sync.start_ms`, 모르면 `null`). 판정 칸은 끝난 사건 객체의 `result`·`other_cls`와 같은 값.
- 자세한 내용은 항목의 `id`로 `GET /api/bb-cases/{id}`.

#### GET `/api/bb-cases/{id}`

**분석 중**: `{"id", "status": "analyzing", "progress": 0~100, "created_at", "updated_at"}`. 앱은 1초 간격으로 다시 부른다.

**분석이 `ok`가 아니게 끝남** (`no_collision` / `unsupported` / `failed`): `{"id", "status", "progress": 100, "created_at", "updated_at", "analysis", "sync", "collision_review"}`. `analysis.reason`(코드)·`analysis.message`(한 문장)를 보여 주고 끝. `no_collision`이면 `collision_review.needed: true`와 사고 순간 후보(아래), 영상이 남아 있으면 `can_pick: true` → `PUT …/collision`.

**끝난 사건** (`needs_answers` / `done`):

| 칸 | 모양 | 뜻 |
|---|---|---|
| `id`, `status`, `progress`, `created_at`, `updated_at` | | `status`: 꼭 답할 질문이 남았으면 `needs_answers`, 아니면 `done` |
| `analysis` | `{"status": "ok", "reason", "message", "analyzer": {"name", "version"}, "video": {"duration_s", "fps", "frames", "width", "height"}, "scenario"}` | 분석기 결과 요약. `scenario`는 가짜 분석기일 때 `{"scenario", "chosen_by", "video_read", "description"}` |
| `sync` | 아래 "시각 맞추기" | 영상 시각 ↔ 차량 기록 시각 |
| `event` | `{"t_event", "t_event_source": "video", "collision_t", "collision_frame", "range"}` | `t_event` = 차량 시계의 충돌 시각(ms, 시작 시각을 모르면 `null`), `collision_t`·`collision_frame` = 영상 안 충돌 순간 ("영상 다시 보기"에서 이 초로 감), `range` = 쓴 차량 기록 구간 |
| `data_quality` | `{"vehicle_record", "sync_grade", "sync_reason", "sync_reason_text", "sync_suspect", "clock_warnings", "samples", "gaps", "fields_missing"}` | `sync_suspect`: 차량 값이 영상 값을 이긴 충돌이 2개 이상 (시각 맞추기가 틀렸을 수 있음). `sync_reason_text`: 시각 맞추기가 `none`인 이유 한 문장(아니면 `null`). `clock_warnings`: 서버 시각과 하루 넘게 다른 시계 (2026-11-11, 아래 "시각 맞추기"). 앱은 아직 이 두 칸을 보여 주지 않음 |
| `parties` | `{"ego": {"label": "내 차", "cls"}, "other": {"label": "상대", "cls"}}` | 상대 `cls`는 판정에 쓴 종류 (사용자 답 > 영상 확실한 값 > 영상 추정값). 질문 보기 이름이라 보행자는 `pedestrian` |
| `other_cls` | `{"field": "parties.other.cls", "value", "label", "source", "confidence", "low_confidence", "chapter", "options", "choices"}` | **상대 종류와 출처** (2026-11-10). `source`: `video`(영상이 확실하게 냄) / `user`(답함) / `guess`(영상 추정값으로 임시 판정, `remaining` 맨 앞에 상대 종류 질문이 있음) / `null`(정보 없음, 엔진이 차대차로 판정). `low_confidence`: 영상이 값을 냈지만 확신도가 0.7(임시값) 미만이라 추정값으로 내림. `chapter`: `car_car` / `car_pedestrian` / `car_bicycle`. 앱은 `source`가 `video`·`guess`일 때 "상대가 {label}이(가) 아니었나요?" 버튼을 띄우고, 고르면 `options` 값으로 `PUT answers`의 `parties.other.cls`를 보낸다 |
| `answers` | `{질문 키: {"value", "source", "evidence"}}` | **`result`(기본 판정)에 쓴 값 전부.** `source`: `user` / `video` / `default`, 내 차 종류만 `vehicle`("차량 정보", 기록이 아니라 차량 종류). `evidence`: 근거 문장(아래). (4.4) 차량 기록 값은 여기 없다 |
| `auto_answers` | `[{"field", "value", "source": "vehicle", "rule", "evidence": {"text", "window", "points"}}]` | 차량 규칙이 확정한 답 (차량 명세 2.5와 같음). (4.4) `result_with_vehicle`에 쓴 것 |
| `remaining` | `[{"field", "question", "answer_type", "options", "choices", "model_guess", "guess_source", "guess_evidence", "guess_choice", "default", "group", "depends_on", "vehicle_hint"}]` | **실제로 답이 필요한 질문** (선택 질문 제외). 질문 화면은 이 목록을 차례로 보여 준다. 지금 판정에는 `model_guess`(없으면 기본값)가 들어가 있음. (4.4) 차량 기록이 답하던 질문(지시등·서행 등)도 여기 남고, 추정값 출처에 `vehicle`은 없다 |
| `remaining[].vehicle_hint` | `{"value", "value_label", "text", "determined", "applied", "reason", "reason_text", "rule"}` \| `null` | (4.4) 그 질문에 대한 차량 기록 값(참고). `value_label` 짧은 이름("켬"), `text` 규칙 문장("사고 6초 전 왼쪽 지시등 켜짐 …"), `determined` 규칙이 확정했는지(아니면 추정), `applied` `result_with_vehicle`에 썼는지, `reason`: `sync_coarse` / `sync_none` / `guess`, `reason_text` 한 문장. `questions[]`·`answered[]`에도 같은 칸 |
| `answered` | `[remaining 한 줄 모양 + "optional", "value", "value_choice"]` | (4.4, 서버 빈틈) 사용자가 답한 질문의 정의와 지금 답. 앱 "답변 고치기" = `answered` + `remaining`. 지금 장에 없는 질문과 조건(`skip_when`·`when_any`)으로 빠진 질문은 뺌. (2026-11-12) 선택 질문(특수 상황·운전자 요인·과속 인과관계)도 들어가고, 그때는 `questions[]` 한 줄의 칸 전부(`option_groups`·`more_options` 등) + `optional: true` |
| `remaining_count` | 정수 | `len(remaining)`. "질문 N개 남음" |
| `questions` | 질문 목록 | 답하지 않은 질문 전부(선택 질문 포함, 1부와 같은 칸). 선택 질문(`optional: true`, 예: 운전자 사정)을 보여 줄 때 씀 |
| `source_conflicts` | `[{"field", "used": {"value", "source"} \| null, "others": [{"value", "source", "evidence"}], "evidence", "kind"}]` | 출처끼리 다른 값 (4.3). `kind`: `user_vs_vehicle` / `user_vs_video` / `vehicle_vs_video` / `guess_mismatch` |
| `answer_conflicts` | `[{"field", "vehicle_value", "user_value", "evidence"}]` | 차량 명세 v0.3 칸 그대로 (`user_vs_vehicle`만) |
| `result` | `{"status": "ok"\|"no_rule", "provisional", "rule_id", "title", "fault_by_party", "base_fault_by_party", "modifiers": [{"label", "party", "delta", "source", "facts", "needs_proof"}], "unverifiable_factors", "auto_filled", "notice", "chapter", "fault_display"}` | 차량 명세 2.7. `provisional`: 남은 질문이 있어 추정값으로 낸 임시 결과. `chapter`·`fault_display`는 아래 "사고 장과 비율 표기". (4.4) **영상·사용자 답·기본값만으로 낸 기본 판정** |
| `result_with_vehicle` | `result`와 같은 모양 \| `null` | (4.4) 기본 판정 + 차량 기록 (우선순위 4.2). 차량 기록을 붙이지 않았으면 `null`. 시각 맞추기 `coarse`면 타이밍 값(지시등·서행·진로 변경 방향)은 여기에도 안 씀, `none`이면 차량 기록을 하나도 안 씀(= `result`와 같음) |
| `vehicle_effects` | `[{"field", "label", "value", "value_label", "summary", "text", "rule", "applied", "reason", "reason_text", "ego_delta", "direction", "fault_by_party_if_applied"}]` | (4.4) 두 판정의 차이를 만든 기록. **결과(도표·비율)가 같으면 `[]`.** `applied: true` = `result_with_vehicle`에 들어가 차이를 만든 값. `applied: false` = 시각 맞추기가 `coarse`/`none`이라 쓰지 않았지만 정확히 맞췄다면 결과가 바뀌는 값(`reason` `sync_coarse`/`sync_none`, 그때 비율 `fault_by_party_if_applied`). `ego_delta`: 내 차 과실 변화(%p, 가감 요소로 못 나누면 전체 차이, 모르면 `null`), `direction`: `ego_more` / `ego_less` / `changed`(도표가 바뀜). `summary` "내 차가 방향지시등을 켜지 않았어요", `text` 차량 규칙 문장 |
| `vehicle_timeline` | 아래 "기록 보기 요약" \| `null` | (4.4) 충돌 전후 차량 기록 요약 (앱 기록 보기 그래프). 차량 기록이나 충돌 시각(차량 시계)이 없으면 `null` |
| `judge_version` | 문자열 | |
| `collision_review` | 아래 "사고 순간 확인 필요" | (2026-11-12) 영상의 사고 순간이 없거나 불확실한지. 끝난 사건과 `ok`가 아닌 사건 모두에 있음 (그 전에 만든 사건은 없음) |

**사고 순간 확인 필요 `collision_review`** (2026-11-12, `analyzer.collision_review`)

```json
{"needed": true, "reason": "low_confidence", "message": "사고 순간이 확실하지 않아요. 영상에서 부딪힌 순간이 맞는지 확인해 주세요",
 "t": 7.4, "t_confidence": 0.2, "threshold": 0.5,
 "candidates": [{"t": 7.4, "frame": 222, "source": "analyzer"}]}
```

| `reason` | 조건 (분석기 출력) |
|---|---|
| `no_collision` | `status: no_collision` (`collision.t: null`) |
| `guess` | `status: ok`이고 `collision.t_source == "guess"` |
| `low_confidence` | `status: ok`이고 `collision.t_confidence < 0.5` (임시값 `analyzer.LOW_T_CONFIDENCE`. A 분석기는 0.8(멈춤 직전 충격) / 0.5(그 밖에 충격을 찾음) / 0.2(못 찾음 → `no_collision`)을 냄) |
| `null` | 확인 필요 없음 (`needed: false`, `candidates: []`) |

- `candidates`: 분석기의 `hints.collision_candidates`(`[{"t", "frame", "source", "reason"}]`, 영상 안 초) 그대로. 분석기가 후보를 안 주고 `collision.t`가 있으면 그 시각 하나(`source: "analyzer"`).
- **HMTM 방어**: `needed`면 시각 맞추기 등급을 `none`으로 둔다 (`sync.reason`: 차량 기록이 있으면 `collision_uncertain`, 없으면 `no_vehicle_record`. `no_collision`은 판정 없음). `sync.t_collision_ms`·`event.t_event`는 `null`이고 차량 기록 값은 하나도 쓰지 않는다: `auto_answers: []`, `result_with_vehicle`은 `result`와 같은 비율, `vehicle_effects: []`, `vehicle_timeline: null`. 판정(`result`)은 영상 값·사용자 답으로 그대로 낸다.
- `PUT answers`로 다시 판정해도 `collision_review`·`sync`는 그대로다. 사고 순간을 바꾸는 것은 `PUT …/collision`뿐이다.
- 앱: `needed`면 결과(또는 `no_collision` 안내) 위에 `message`와 "영상에서 사고 순간 확인" 버튼을 띄울 수 있다. 사건 목록 한 줄에는 `collision_review_needed`(bool)·`collision_pick_until`.

**고르기 칸 (2026-11-12, `api.pick_window`)**

| 칸 | 뜻 |
|---|---|
| `can_pick` | 영상이 서버에 남아 있어 `PUT …/collision`을 받는지 (`needed`이고 기한 전) |
| `pick_until` | 고르기 기한(epoch ms) = 처음 분석이 끝난 때 + 7일. `needed`가 아니면 `null` |
| `expired` | 기한이 지나 영상을 지웠음 (`can_pick: false`, `needed`는 그대로 `true`) |
| `picked` | 고른 순간으로 다시 분석해 판정됨: `{"t", "picked_at"}`. 이때 `needed: false`, `reason: null` |
| `last_pick` | 고른 순간으로도 판정하지 못함: `{"t", "picked_at", "status", "reason", "message"}`. 결과는 고르기 전 분석으로 되돌림 |

#### PUT `/api/bb-cases/{id}/collision` (사고 순간 고르기, 2026-11-12)

```json
{"t": 7.4}
```

- `t` = 영상 안 초 (0 이상, 영상 길이 이하). 앱은 `collision_review.candidates`의 `t`를 보여 주거나 "영상 다시 보기"에서 멈춘 시각을 보낸다.
- 받을 때: `collision_review.needed`이고 영상이 남아 있는 사건(`can_pick: true`). `no_collision`뿐 아니라 판정이 된 불확실 사건(`guess`·`low_confidence`)도 받는다.
- 응답 `202`: 분석 중 객체(`{"id", "status": "analyzing", "progress": 0, "created_at", "updated_at"}`). 앱은 `POST`처럼 `GET`을 폴링한다.
- 서버는 사건을 `analyzing`으로 돌리고 분석 줄에 넣는다(fake = API 스레드, mtm = 작업자, 3.4). 분석기에 `collision_t`를 넘기고, 결과가 `ok`면 `facts.collision`을 고른 순간으로 쓴다
  (`t`, `frame`, `t_source: "user"`, `t_confidence: null`, 분석기가 낸 값은 `bb_facts.hints.collision_pick`). 그러면 `collision_review.needed: false`라 시각 맞추기·차량 기록을 다시 쓴다.
  판정되면 영상을 지운다(`HMTM_KEEP_VIDEO=1`이면 보관). 그 전에 한 답(`answers`)은 그대로 쓴다.
- 고른 순간으로도 판정하지 못하면(`no_collision`·`unsupported`·`failed`) **고르기 전 분석 결과로 되돌리고**(전 판정·답 그대로) `collision_review.last_pick`을 남긴다. 영상은 기한까지 남아 다시 고를 수 있다.
- 분석기 쪽: 가짜 분석기는 시나리오 `fake.on_pick`(다른 시나리오 이름)이 있으면 그 시나리오로 답한다(`no_collision_pick` → `right_turn_left_straight`). MTM 분석기에는 `video_analyzer.analyze(..., collision_t=초)`로 넘긴다(A가 그 시각을 충격 프레임으로 두고, 상대 고르기·상대 종류·장면이 모두 그 충격 프레임을 읽음, 2026-11-13).
- 오류: `422 request_invalid`(`{"t"}` 모양 아님), `422 collision_invalid`(숫자가 아니거나 영상 밖), `409 bb_case_analyzing`(분석 중), `409 collision_not_needed`(확인 필요 없음, 이미 고름),
  `410 video_gone`(기한이 지나 영상을 지움), `503 analyzer_not_ready`(mtm 가중치 준비 안 됨). 오류면 사건은 그대로.

**사고 장과 비율 표기** (2026-11-10)

- `result.chapter`: 판정 엔진이 고른 장(`car_car` / `car_pedestrian` / `car_bicycle`). 판정을 못 하면(`no_rule`) 질문을 고른 장.
- `result.fault_by_party`는 장과 관계없이 **두 당사자 합 100**이다 (앱의 막대·"내 차 / 상대" 칸은 그대로 씀).
- 차대보행자 장은 인정기준이 **보행자 과실만** 정한다 (예: 보20 "보행자 20"). 그래서 `fault_by_party.other` = 보행자 과실, `fault_by_party.ego` = 100 − 보행자 과실로 준다.
- `result.fault_display`: 앱이 머리 숫자로 쓸 표기. 판정이 없으면 `null`.

| 장 | `fault_display` 예 |
|---|---|
| `car_pedestrian` | `{"kind": "pedestrian_only", "party": "other", "value": 30, "text": "보행자 과실 30%", "note": "차대보행자 기준은 보행자 과실만 정해요. 내 차 몫은 나머지 70%예요"}` |
| `car_car`, `car_bicycle` | `{"kind": "ratio", "party": null, "value": null, "text": "내 차 60 : 상대 40", "note": null}` |

- 앱 표시: `kind`가 `pedestrian_only`이면 큰 글씨로 `text`("보행자 과실 30%"), 막대 아래에 `note`. `ratio`면 지금처럼 "내 차 60 : 상대 40".

**상대 종류 바꾸기**: `PUT answers`에 `parties.other.cls`(보기 `car` `truck` `bus` `two_wheeler` `bicycle` `farm_machine` `pedestrian`, 분석기 이름 `person`도 받음)를 넣으면 영상이 확실하게 낸 값이어도 사용자 답이 이긴다 (`source_conflicts`에 `user_vs_video`). 서버는 저장한 `bb_facts`로 그 장의 질문·도표로 다시 판정한다. 이전 장의 질문 답이 섞여 와도 받고, 지금 장에 쓰지 않는 답은 판정에 넣지 않는다.

**보행자·자전거 장 질문 키** (값은 `options`·`choices` 짝): 보행자 장은 차대차 전용 기본 질문(상대 진행 방향·온 길, 상대 신호, 더 넓은 길, 진입 순서)을 빼고 `parties.other.crosswalk_distance`(`on` / `within_10m` / `10_30m` / `over_30m` / `no_crosswalk`, 대표 거리 5·20·40m로 판정), `parties.other.ped_place_other`, `parties.other.overpass_distance`, `road.crosswalk_signal`, `parties.other.ped_signal_at_start`·`_impact`, `parties.ego.signal_at_entry`, `parties.ego.impact_after_intersection`, `parties.ego.passed_crosswalk`, `parties.ego.right_turn_signal`, `parties.other.ped_activity`, `parties.other.crossing_road_width`, `road.sidewalk_separated`, `parties.other.sidewalk_closed`, `road.center_line`, `parties.other.roadway_walk_position`을 조건(`depends_on`)에 맞을 때 묻는다.
2026-11-11부터 보행자 장에 더한 질문 (`docs/backend-gaps-notes.md` 2절): 도표 선택용 `road.expressway`(횡단보도가 없거나 30m 넘게 떨어졌을 때)·`parties.other.expressway_walk_reason`(`justified`/`none`, 보35·보36),
그 뒤 가감 요소 `parties.other.vulnerable_type`(`child`/`elderly`/`disabled`/`none`), `road.protection_zone`(같은 값), `road.ped_visibility`(`night`/`obstructed`/`bad_weather`/`clear`, 영상이 밤·악천후를 확실히 내면 안 물음),
고속도로일 때 `parties.other.on_shoulder`·`road.easy_walk_area`, 이유가 있을 때 `road.ped_warning_sign`. 고속도로라고 답하면 장소·건넌 도로 폭 질문은 `remaining`에서 빠진다.
운전자 요인 `parties.ego.driver_factors`(여러 개 고르기, 차대차와 같은 보기)는 선택 질문(`questions`에만). 자전거 장은 차대차 질문 전부 + `parties.other.entry_from`(교차로 아닌 길에서도), `on_bike_crossing`, `crossing_road`, `bike_lane_type`, `parties.<ego|other>.approached_right_edge`.

**질문 키와 값**: 자기 차 기준 보기를 쓴다 (차량 명세 2.6). 상대가 온 길 `parties.other.entry_from`은 `left`/`right`/`opposite`/`same`, 더 넓은 길 `road.wider_road`는 `equal`/`mine`/`theirs`. 보기 값과 화면 이름은 질문의 `options`·`choices` 순서대로 짝이다.

**근거 문장 `answers[키].evidence`** (모든 출처에 있음, "~했어요" 말투)

| `source` | 예 |
|---|---|
| `vehicle` | 차량 규칙 문장 그대로: "사고 6초 전 오른쪽 지시등 켜짐 (사고 때까지 켜져 있음)". 내 차 종류는 "내 차는 승용차였어요 (차량 정보)" |
| `video` | "내 차가 우회전했어요 (17.5초)" (분석기가 시각을 주면 초를 붙임) |
| `user` | "상대는 화물차였어요 (직접 답했어요)" |
| `default` | "교차로에 신호등이 없었어요 (영상 추정)". 괄호 안은 `영상 추정값` / `차량 기록 추정값` / `기본값` |

`remaining[].guess_evidence`는 추정값의 근거: 영상 추정이면 "영상으로는 내 차가 직진한 것 같아요 (추정)", 차량 추정이면 차량 규칙 문장.

**시각 맞추기 `sync`**

```json
{"start_ms": 1762666212000, "start_source": "filename",
 "offset_ms": -1300, "method": "speed_xcorr+impact", "score": 1.0,
 "grade": "fine", "reason": null, "t_collision_ms": 1762666228900,
 "candidates": [{"source": "filename", "start_ms": 1762666212000}],
 "fine": {"reason": null, "offset_ms": -1300, "score": 1.0,
          "offset_candidates": [{"offset_ms": -1300, "score": 1.0}, {"offset_ms": -200, "score": 0.926}],
          "impact": {"t_ms": 1762666229100, "decel_kmh_s": 50.7, "offset_ms": -1100, "matched": true}},
 "params": {...}}
```

| `grade` | 언제 | 차량 기록을 쓰는 범위 | `reason` (없으면 `null`) |
|---|---|---|---|
| `fine` | 속도 모양 상관 ≥ 0.7이고 충격 기준점이 0.5초 안 (5.3 임시값). `offset_ms`로 보정 | 전부 (지시등·서행·진로 변경 방향도 확정 답) | — |
| `coarse` | fine이 안 되고, 시작 시각이 파일 이름·메타데이터·앱 값이며 차량 기록이 충돌 3초 전부터 덮음. `offset_ms` 0 | 후진·서 있었음만 확정. 지시등·서행·진로 변경 방향은 추정값(`guess_source: vehicle`) | — |
| `none` | 그 밖, 또는 영상 사고 순간이 불확실 (`collision_review`) | 쓰지 않음 | `no_start_time` / `no_vehicle_record` / `no_collision_time` / `collision_uncertain`(사고 순간이 추정이거나 확신도가 낮음, 2026-11-12) / `start_time_unreliable`(수정 시각뿐) / `vehicle_record_not_covering`(겹치지만 충돌 3초 앞~충돌을 못 덮음) / `vehicle_clock_mismatch`(올린 기록이 영상 구간과 하나도 안 겹침, 2026-11-11. 전에는 `no_vehicle_record`로 보였음) |

- **이유·시계 경고 (2026-11-11, 명세 6.1)**: `reason_text` = `none`일 때 이유 한 문장(아니면 `null`). `vehicle_gap` = `vehicle_record_not_covering`·`vehicle_clock_mismatch`일 때
  `{"need": {from, to}, "vehicle_range": {from, to}, "gap_ms"}` (`need`는 충돌 3초 앞~충돌, 충돌 시각이 없으면 영상 구간. `gap_ms`: 기록이 앞이면 음수, 뒤면 양수, 겹치면 0. 0이 아니면 `reason_text` 끝에 "(차량 기록이 영상보다 2.0시간 뒤예요)").
  `clock_warnings` = `[{"kind": "video_clock"|"vehicle_clock", "source", "t_ms", "server_ms", "diff_ms", "direction": "ahead"|"behind", "message"}]`:
  촬영 시작 시각(`start_ms`)이나 올린 차량 기록 구간(서버 시각에 가까운 끝)이 사건을 받은 서버 시각(`created_at`)과 하루 넘게 다르면. 오류가 아니라 경고이고 판정은 그대로다.
  `no_collision` 등 판정하지 않은 사건도 `sync`에 있다. `data_quality`에 같은 값을 복사한다.
- `candidates`: 촬영 시작 시각 후보(믿는 순서). `fine`: 정밀 맞추기를 해 봤으면 그 결과(안 됐으면 `fine.reason`: `no_vehicle_speed` / `no_ego_motion` / `no_speed_variation` / `low_correlation` / `no_impact` / `impact_mismatch` / `vehicle_record_not_covering`), 차량 기록이 없으면 `null`.
- 앱 표시 예: `fine` "시각 정확히 맞춤", `coarse` "시각 대략 일치", `none` + `no_vehicle_record` "차량 기록 없음", 그 밖의 `none` "시각 확인 안 됨".

**기록 보기 요약 `vehicle_timeline`** (4.4)

```json
{"t0_ms": 1762666228900, "from_s": -15.0, "to_s": 5.0, "step_s": 0.2, "collision_s": 0.0, "video_collision_t": 18.2,
 "sync_grade": "fine", "aligned": true, "speed": [[-15.0, 38.2], [-14.8, 38.5], ...], "speed_max": 43.2,
 "turn_signal": [{"dir": "LEFT", "from": -6.0, "to": 5.0}], "brake": [{"from": 0.0, "to": 5.0}],
 "gear": [{"value": "D", "from": -15.0, "to": 5.0}], "gaps": []}
```

- 시각은 **충돌 기준 초**(앞이 음수). `t0_ms` = 충돌 시각(차량 시계, `sync.t_collision_ms`). 구간은 충돌 15초 전~5초 뒤를 차량 기록 구간으로 자름.
- `speed`: 0.2초마다 `[초, km/h]`(기록이 없으면 km/h가 `null`, 최대 101점). `turn_signal`·`brake`·`gear`: 켜진(그 값인) 구간. 지시등은 깜빡임을 이어 붙인 구간(차량 명세 4.1).
- `aligned`: 시각 맞추기가 `fine`(또는 `user`)이라 영상 충돌 순간과 그래프의 0초가 맞는지. 아니면 앱이 "시각을 대략만 맞췄어요"를 보인다.

#### PUT `/api/bb-cases/{id}/answers`

```json
{"answers": {"road.signal_present": false, "parties.other.entry_from": "right"}}
```

- **지금까지의 답 전부**를 보낸다 (통째로 바꿈, 차량 명세 2.2와 같은 규칙). `{}`이면 답을 모두 지운 처음 결과.
- 서버는 저장한 `bb_facts`(분석기 결과)·차량 기록·`sync`로 **처음부터 다시** 합치고 판정한다. 영상은 이미 지웠으므로 다시 분석하지 않는다 (`analysis`·`sync`는 그대로).
- 사용자 답이 이긴다 (`user > vehicle > video > default`). 차량·영상 값과 다르면 `source_conflicts`에 `user_vs_vehicle` / `user_vs_video`로 남고, `user_vs_vehicle`은 `answer_conflicts`에도 남는다.
  답 키가 다른 장면 값(보행자 `road.ped_visibility`·차대차 특수 상황 "밤이었음" ↔ 영상 `road.night` 등)도 사용자 답으로 판정하고 `source_conflicts`의 `field`는 장면 키(`road.night`)다 (2026-11-11, `docs/backend-gaps-notes.md` 4절).
- 여러 개 고르기(특수 상황 `situation.special`, 운전자 요인 `driver_factors`)는 **고른 보기만 사용자 답**이다. 안 고른 보기는 답 없음(영상 값, 없으면 기본값)이고, `[]`도 답 없음.
  전부 "아니요"는 보기 `none`("해당 없음 (모두 아니요)")을 혼자 고를 때만 (다른 보기와 같이 고르면 `422 answer_invalid`) (2026-11-11, `docs/backend-gaps-notes.md` 5절).
- 운전자 요인(`parties.<ego|other>.driver_factors`)에 과속 보기를 고르면 `parties.<같은 당사자>.avoidable_at_limit`("제한속도를 지켰다면 사고를 피할 수 있었나요?", 예 / 아니요)가 `remaining`에 나온다. 예일 때만 과속 가산 (2026-11-11, 같은 문서 3절).
- 지금 질문에 없는 키라도 질문 키 모양이면 받는다 (앞 답을 바꿔 사라진 질문의 답이 섞여 와도 됨, 차량 명세 2.2).
- 응답 `200`: 끝난 사건 객체 (GET과 같음, `updated_at`이 바뀜).
- 오류: `422 request_invalid`(JSON 아님), `422 answers_shape`(`answers`가 객체가 아님), `422 answer_invalid`(없는 질문 키, 보기에 없는 값), `409 bb_case_analyzing`(분석 중), `409 bb_case_not_judged`(`no_collision`·`unsupported`·`failed` 사건). 오류면 저장하지 않는다.

#### DELETE `/api/bb-cases/{id}`

- `204`, 본문 없음. 되돌릴 수 없다.
- 지우는 것: 행 하나(meta, 차량 기록 원본, `bb_facts`, `sync`, 답, 규칙 결과, 응답)와 사건 폴더(분석 중인 영상, `HMTM_KEEP_VIDEO=1`로 남긴 영상, 분석기 중간 파일).
- 분석 중이면 분석도 멈춘다 (분석기의 진행률 알림에서 멈추고, 분석 스레드가 사건 폴더를 다시 지움). 줄에서 기다리던 사건은 분석하지 않는다.
- 탈퇴(`DELETE /api/me`)하면 그 회원의 블랙박스 사건이 모두 이렇게 지워진다.

#### DELETE `/api/bb-cases` (내 사건 전부, 2026-11-10)

- `200` `{"deleted": 지운 개수}`. 사건마다 위 DELETE와 같이 지운다(분석 중이면 분석도 멈춤). 남의 사건은 그대로.
- 앱 "모든 기록 삭제"의 "서버의 분석 사건도 함께 지우기"가 이 주소 하나를 부른다 (전에는 목록을 돌며 하나씩 지움).

## 4. 정보 우선순위와 출처

### 4.1 출처 네 가지

| 출처 | 뜻 | 판정 엔진에 넘기는 `source` | "입증 필요" |
|---|---|---|---|
| `user` | 사용자 답 | `user` (`to_assumptions` 경로) | 붙음 (엔진 규칙) |
| `vehicle` | 차량 기록 규칙의 자동 답변·사실 | `vehicle` | 안 붙음. 단 **기본 판정(`result`)에는 넣지 않고** `result_with_vehicle`에만 넣는다 (4.4, D6을 바꿈) |
| `video` | 블랙박스 분석기의 확실한 값 (`value`가 있음) | `model` (FACTS 이름) | 안 붙음 (확정 Q15) |
| `default` | 답이 없어 기본값·추정값(`guess`·`model_guess`)으로 채움 | 값 객체 없이 그냥 값 | 안 붙음. 결과는 `provisional`이 될 수 있음 |

### 4.2 우선순위 (확정 Q9)

**같은 항목에 값이 여럿이면: `user` > `vehicle` > `video` > `default`.**

- **user가 맨 위**: 지금 규칙(D9) 그대로. 사용자가 고치면 사용자 답으로 판정하고, 다른 출처와 다르면 기록한다.
- **vehicle > video**: 차량 기록은 내 차를 직접 잰 값이고, 영상은 화면으로 어림한 값이다. 단 **차량 기록이 실제로 정한 항목만** 해당한다 (차량 규칙이 정하는 것은 내 차 `movement=reverse`, `turn_signal_used`, `slowed_before_entry`, `lane_change_dir`, `stationary_at_collision`, `stopped_before_entry`, `cls`). 상대·도로·신호 색은 차량 기록에 없으므로 영상과 다툴 일이 없다.
- **시각 맞추기가 믿을 만하지 않으면 시각에 기대는 차량 값은 쓰지 않는다** (5.3의 등급). 이때는 그 항목이 `video` 또는 질문으로 내려간다.
- **추정값끼리**(정하지 못한 값의 `model_guess`): 차량 추정(`guess_source: "vehicle"`)과 영상 추정(`guess_source: "video"`)이 **같으면** 그 값, **다르면 미리 고르지 않는다**(`model_guess: null`). 두 근거 문장을 모두 `guess_evidence`에 보여 준다. 예: 지시등은 LEFT(차량)인데 화면은 오른쪽으로 꺾음(영상).
- **확실한 값과 추정값**: 어느 출처든 확실한 값(`vehicle` 자동 답변, `video`의 `value`)이 추정값보다 앞선다. 예: 차량 기록은 회전을 추정만 하고(4.3) 영상이 `right_turn`을 확실히 냈으면 `video`.
- 항목 하나에 대해 이 규칙으로 **판정에 쓸 값 하나**와 그 출처를 정하고, `answers`에 `{"value", "source"}`로 남긴다 (차량 명세 2.5와 같은 칸, `source`에 `video` 추가).

**guess_source** (질문의 추정값 출처): `vehicle` / `video` / `default` / `null` (차량 명세 3절의 셋에 `video`를 더함). (4.4) 기본 판정의 질문에는 `vehicle`이 없고, 차량 기록 추정값은 `vehicle_hint`로 간다. `result_with_vehicle` 판정 안에서만 이 절의 규칙대로 `vehicle` 추정값을 쓴다.

### 4.3 충돌 기록

차량 명세의 `answer_conflicts`(사용자 답 ↔ 자동 답변)를 넓혀, **출처끼리 다른 값을 모두** 한 곳에 남긴다: **`source_conflicts`** (확정 Q7).

```json
"source_conflicts": [
  {"field": "parties.ego.movement",
   "used": {"value": "reverse", "source": "vehicle"},
   "others": [{"value": "straight", "source": "video", "evidence": "화면이 앞으로 흘렀어요 (13.2초)"}],
   "evidence": "사고 직전 3초 중 2.4초 동안 기어가 R(후진)이었어요",
   "kind": "vehicle_vs_video"}
]
```

| `kind` | 언제 | 앱에서 |
|---|---|---|
| `user_vs_vehicle` | 지금 `answer_conflicts`와 같음 | "차량 기록과 다르게 입력함" |
| `user_vs_video` | 사용자가 영상의 확실한 값을 고침 | "영상 분석과 다르게 입력함" |
| `vehicle_vs_video` | 차량 값이 영상 값을 이김 | 결과 화면 참고. **여러 항목에서 나면 시각 맞추기가 틀렸을 가능성**을 `data_quality`에 경고 (5.3) |
| `guess_mismatch` | 추정값끼리 다름 (미리 고르지 않음) | 질문 화면에 두 근거 |

- 하위 호환: `answer_conflicts`는 차량 명세 v0.3이 정한 칸이라 `user_vs_vehicle`만 담아 그대로 둔다 (확정 Q7).
- `modifiers[].source`(차량 명세 2.7) 규칙도 넓힌다: 근거 사실 중 하나라도 `user`면 `user`, 아니면 `vehicle`, 아니면 `video`, 아니면 `default`.

### 4.4 차량 기록은 참고 자료 (2026-11-10 설계 변경, D6을 바꿈)

전에는 차량 기록 값을 "입증된 것"으로 보고 판정에 바로 넣었다(D6: 차량 기록 가감 요소는 입증 필요 없음). 하지만 차량 기록은 앱이
차 안에 남긴 것이라 보험사·법원에 그대로 인정된다는 보장이 없다. 그래서 **판정은 영상·사용자 답 기준으로 내고, 차량 기록은
"입증할 수 있으면 과실이 이렇게 바뀔 수 있다"를 보여 주는 참고 자료**로 쓴다. 기록을 제출·내보내는 기능은 만들지 않는다.

| 판정 | 쓰는 값 | 응답 칸 |
|---|---|---|
| 기본 (base) | 사용자 답 > 영상 확실한 값 > 영상 추정값·기본값. 내 차 종류(차량 정보)는 씀 | `result`, `answers`, `remaining`, `status` |
| 차량 기록 포함 (with_vehicle) | base + 차량 규칙 (4.2 우선순위 그대로, 시각 맞추기 등급 5.3 그대로) | `result_with_vehicle`, `auto_answers`, `source_conflicts`, `answer_conflicts`, `data_quality` |

- **질문**: 차량 기록이 답하던 질문(지시등·서행·진로 변경 방향 등)도 base 기준으로 `remaining`에 나온다. 사용자가 답하면 두 판정 모두 사용자 답(4.2: user가 맨 위). 차량 기록 값은 질문마다 `vehicle_hint`(참고)로 붙는다.
- **차이를 만든 기록** `vehicle_effects`: with_vehicle에서 출처가 `vehicle`이고 base와 값이 다른 항목 중, 그 항목이 근거인 가감 요소가 내 차 과실을 바꾼 것. 가감 요소로 못 나누고 도표가 바뀌었으면(예: 후진) 바뀐 항목 모두. 두 판정의 (상태, 도표, 비율)이 같으면 `[]`.
- **정밀 시각 맞추기 원칙은 그대로**: `coarse`면 타이밍 값(지시등·서행·진로 변경 방향)은 with_vehicle에도 쓰지 않고, `none`이면 차량 기록을 하나도 쓰지 않는다. 대신 서버가 "정확히 맞췄다면(fine)" 판정을 한 번 더 내 보고, with_vehicle과 다르면 그 값을 `vehicle_effects`에 `applied: false` + `reason`(`sync_coarse` / `sync_none`) + `fault_by_party_if_applied`로 남긴다 (충돌 시각을 차량 시계로 모르면 하지 않음).
- **"입증 필요" 표시**: with_vehicle의 차량 가감 요소는 판정 엔진 규칙대로 `needs_proof: false`다. 앱은 with_vehicle 카드 전체를 "차량 기록을 입증할 수 있으면"으로 묶어 보여 주므로 따로 붙이지 않는다.
- **차량 사건(`/api/vehicle-cases`)도 같은 원칙**: `result` = 사용자 답·기본값, `result_with_vehicle` = 자동 답변 포함, `questions[].vehicle_hint`, `vehicle_effects`, `vehicle_timeline`(차량 시계 하나라 `sync_grade: "vehicle"`). 기존 시험의 뜻이 바뀐 곳은 `docs/bb-flow-notes.md` 끝 절.

## 5. 영상 시각과 차량 기록 시각 맞추기

### 5.1 왜 필요한가

- 차량 규칙은 사고 시각 `T` 기준 몇 초 앞을 본다 (지시등 `LEAD` 2~5초, 서행 `PRE` 1.5초 구간). 영상의 충돌 시각을 차량 기록 시각으로 바꿀 때 **0.5초만 틀려도** 지시등·서행 판정이 바뀔 수 있다.
- 블랙박스 시계와 차량(앱) 시계는 다른 시계다. 앱 기록 시각은 `System.currentTimeMillis()`(차량 명세 2.1)이고, 블랙박스는 자기 시계로 파일 이름·메타데이터를 쓴다.

### 5.2 영상 촬영 시각의 출처 (거친 값)

| 순서 | 출처 | 내용 | 믿음 |
|---|---|---|---|
| 1 | 빌트인 캠이 차량과 같은 시계를 쓰면 그 기록 | **(확인 필요)** 차량 내장 블랙박스가 차량 시각을 쓰는지, 파일에 시각을 어떻게 남기는지 | 높음 (같은 시계면 오차 작음) |
| 2 | 파일 이름 | 많은 블랙박스가 `YYYYMMDD_HHMMSS` 꼴로 이름을 지음(예: `20261109_143012_F.mp4`, `EVT_…`, `REC_…`). **(확인 필요)** 제조사별 형식, 그 시각이 **녹화 시작**인지 **끝·이벤트 시각**인지, 시간대(대개 현지 시각, 시간대 표시 없음) | 중간. 블랙박스 시계가 GPS로 맞춰지지 않으면 수 초~수 분 틀릴 수 있음 |
| 3 | 영상 메타데이터 `creation_time` (mp4 `mvhd`) | 앱에서 `MediaMetadataRetriever.METADATA_KEY_DATE`로 읽을 수 있음. **(확인 필요)** UTC인지 현지 시각을 UTC로 잘못 적었는지, 시작 시각인지 | 낮음~중간 |
| 4 | 화면 시각 표시(OSD) | 영상 위에 찍힌 날짜·시각. 분석기가 글자를 읽으면 `clock.osd_start_ms` (2차) | 중간 (1초 단위) |
| 5 | 파일 수정 시각 | 대개 녹화 **끝** 시각 → 시작 = 수정 시각 − 길이 | 낮음 (복사하면 바뀜) |
| 6 | 사용자 | 앱에서 시각을 직접 고침 | 사람 기억 수준 |

- 앱이 파일을 고를 때 2·3·5를 읽어 `meta.recorded_at`에 **후보를 모두** 보낸다 (`[{source, start_ms}]`). 서버가 5.3에서 고른다.
- 시간대: 파일 이름 시각은 기기 시간대(한국은 `Asia/Seoul`, UTC+9)로 보고 epoch ms로 바꾼다. 시간대를 모르면 ±9시간 후보를 둘 다 시험할 수 있다(5.3이 고름).

### 5.3 정밀 맞추기 (서버, 확정 Q11)

거친 시작 시각 `S0` 주변에서 시차 `offset`을 찾아 `영상 t초 = S0 + offset + t×1000 (차량 ms)`로 만든다.

1. **속도 모양 맞추기**: 영상 `ego_motion.speed_proxy`(단위 없음)와 차량 `speedKmh`를 같은 0.1초 간격으로 놓고, 둘 다 표준화(평균 0, 표준편차 1)한 뒤 `offset`을 −L~+L(기본 ±15초, 거친 값이 파일 수정 시각뿐이면 ±60초)에서 옮기며 상관이 가장 큰 곳을 찾는다. 출발·정지가 있는 영상에서 잘 맞는다.
2. **기준점 맞추기**: 영상 충격 시각(`collision.t`, `jolt_t`)과 차량 급감속 최대 시각(속도 기울기 최소), 앱의 급제동 북마크(이벤트 파일 이름의 감지 시각, 차량 명세 1절)를 맞춘다. 급제동 감지는 급제동 시작 0.5~1초 뒤라는 점(차량 명세 4.1)을 감안한다.
3. **검산**: 영상 `moving`(달림·멈춤)과 차량 속도 ≤ 2km/h 구간, 영상 좌우 흐름과 지시등·후진 기어가 맞는지 본다. 4.3의 `vehicle_vs_video` 충돌이 많으면 신뢰도를 내린다.

**결과 (`sync`)**

```json
"sync": {"start_ms": 1762666212000, "start_source": "filename",
         "offset_ms": -1300, "method": "speed_xcorr+impact", "score": 0.83,
         "grade": "fine", "candidates": [{"offset_ms": -1300, "score": 0.83}, {"offset_ms": 2100, "score": 0.41}]}
```

등급 기준값(상관 0.7·0.4, 0.5초)은 **임시값**으로 확정하고 실차 영상으로 조정한다 (Q11). 사용자 확인 화면(`PUT /sync`)도 이 등급으로 띄운다.

| 등급 `grade` | 기준 (임시값) | 차량 규칙 쓰는 범위 |
|---|---|---|
| `fine` | 속도 모양 상관 ≥ 0.7이고 충격 기준점과 0.5초 안에서 맞음, 또는 같은 시계(5.2의 1) | **전부** |
| `coarse` | 상관 0.4~0.7, 또는 기준점 하나만 맞음 (오차 2초 안쪽으로 봄) | 시각에 덜 민감한 것만: 후진(3초 구간 60%), 서 있었음. 지시등·서행은 **추정값으로만** (자동 답변 안 함) |
| `none` | 맞출 근거 없음 (영상이 내내 서 있음, 차량 기록이 영상 구간을 못 덮음 등) | **쓰지 않음.** 사용자에게 시각 맞추기를 묻거나(`PUT /sync`) 영상만으로 판정 |

- 사용자 확인: `coarse`·`none`이면 앱이 "영상의 이 장면(충돌)이 차량 기록의 이 시각(급제동)이 맞나요?"를 보여 줄 수 있다 (`PUT /sync`로 `offset_ms`를 정하면 `grade: user`, 전부 사용).
- 블랙박스 시계가 영상 하나 안에서 흐르는(drift) 정도는 영상 길이(수십 초)에서는 무시한다.

### 5.4 차량 규칙의 기준 시각

- `T = S0 + offset + collision.t × 1000` (ms, 차량 시계).
- `t_event_source`는 **`manual`로 넘긴다.** 영상의 충돌 시각은 "부딪힌 순간"이라 `manual`의 뜻(차량 명세 4.1: 사용자가 고른 부딪힌 순간)과 같고, `hard_brake`의 "직전 1.5초 제외"는 필요 없다. `rules.py`는 고치지 않는다. 저장할 때는 원래 출처(`video`)를 따로 남긴다.
- `collision.t`가 없고(`no_collision`) 사용자가 충돌 시각을 고르면 그 값으로 같은 계산을 한다.

### 5.5 루프 CSV에서 구간 고르기 (앱)

1. 앱이 고른 영상의 길이 `D`(`MediaMetadataRetriever.METADATA_KEY_DURATION`)와 거친 시작 시각 후보 `S0`를 읽는다.
2. 구간 `range = [S0 − M, S0 + D + M]`, 여유 `M` = 15초(제안). 시작 시각 출처가 파일 수정 시각뿐이면 `M`을 늘린다.
3. 루프 CSV(`files/loop/seg_<분>.csv`, 72시간)에서 이 구간의 줄을 잘라 차량 명세 1절 변환표대로 `samples`로 바꾼다. 분 경계를 넘으면 이어 붙인다.
4. 구간 길이: 블랙박스 이벤트 영상은 보통 수십 초~1분 **(확인 필요: 실제 쓰는 블랙박스)**. 1분 영상 + 여유 30초 = 90초라 지금 제한(120초) 안이지만, 상시 녹화 파일(1~3분)이면 넘는다. 블랙박스 사건은 제한을 `D + 2M`, 최대 300초로 둔다 (확정 Q12). 100ms 샘플링이면 300초에 3,000개라 개수 제한(20,000)은 여유가 있다.
5. 구간에 기록이 없으면(72시간 지남, 앱이 꺼져 있었음) 차량 기록 없이 올린다 → 영상만으로 판정.

## 6. 지금의 `/api/vehicle-cases` 처리

| 안 | 내용 | 장단 |
|---|---|---|
| (가) **테스트·데모용으로 그대로 둠 (확정 Q3)** | 코드·명세(v0.3)를 고치지 않고 둔다. 명세 맨 위에 "제품 흐름은 블랙박스 사건(`docs/design-blackbox.md`). 이 주소는 영상 없이 차량 규칙만 시험하는 용도"라고 적음. 블랙박스 흐름은 이 코드의 모듈을 불러 씀 | 236개 테스트와 계약 시험이 그대로 살아 있어, 블랙박스 흐름을 만드는 동안 차량 규칙이 깨지는지 바로 앎. 영상이 없는 상황(블랙박스가 없거나 파일을 못 가져옴)의 대체 경로로도 씀. 주소가 둘이라 앱이 헷갈리지 않게 앱에서는 숨김 |
| (나) 새 흐름으로 합침 | `/api/bb-cases`가 "영상 없음"도 받게 하고 `/api/vehicle-cases`를 지움 | 주소 하나. 하지만 "영상이 필수"라는 새 방향과 어긋나고, 지금 테스트를 옮겨야 함 |
| (다) 지움 | | 재사용할 코드는 남기고 주소만 지움. 데모 경로가 없어짐 |

- (가)로 두되, **블랙박스 흐름이 쓰는 공통 코드를 바꿀 때마다 차량 사건 테스트도 같이 돌린다.** 나중에 블랙박스 흐름이 자리 잡으면 (나)·(다)를 다시 정한다 (확정 Q3: 지금은 (가)).

## 7. 앱 흐름 초안

```
[사고 후]
1. 블랙박스 영상 고르기 ──────────── 아래 "영상 가져오기" (Q14 대기. 개발은 USB + DocumentsUI 지정)
   - 고른 파일의 길이·촬영 시각 후보(파일 이름, 메타데이터, 수정 시각)를 읽음
   - 촬영 시각이 이상하면(미래, 72시간보다 오래됨) "촬영 시각을 확인해 주세요"
2. 차량 기록 자동 첨부 ──────────────  루프 CSV에서 [시작 − 15초, 끝 + 15초] 잘라 samples (5.5)
   - 기록이 없으면 "차량 기록이 없어 영상으로만 판단해요" 안내하고 계속
3. 업로드 (POST /api/bb-cases) ─────  영상 + meta + vehicle. 진행 막대(업로드 %)
4. 분석 중 (GET 폴링, progress) ────  가짜 분석기면 바로 끝
   - no_collision → "부딪힌 순간을 골라 주세요" (영상 재생 화면에서 고름 → PUT /collision)
   - unsupported → 안내하고 끝 ("블랙박스 앞 카메라 영상만 분석할 수 있어요")
   - 시각 맞추기 coarse/none → "영상의 충돌 장면 = 차량 기록의 급제동 시각이 맞나요?" (PUT /sync)
5. 질문 (남은 질문만) ───────────────  각 질문에 미리 고른 값과 출처 표시
   - 영상으로 정함 / 차량 기록으로 정함 / 기본값 (guess_source)
   - 출처끼리 다르면 두 근거를 함께 보여 줌 (4.3)
   - PUT /answers → 바로 갱신
6. 결과 ─────────────────────────────  과실비율, 적용 도표, 가감 요소(출처별 표시), "다르게 입력함" 표시
   - 근거: 앱 기기의 원본 영상 위 충돌 시각 표시 + 차량 기록 그래프(속도·지시등·브레이크)를 같은 시간축에
     (서버는 분석 뒤 영상을 지우므로 앱이 고른 파일을 다시 연다, Q13)
7. (필요하면) 삭제 ──────────────────  DELETE
```

**영상 가져오기 (Q14 대기: 실차 확인)**

- **개발은 (나) USB·SD + DocumentsUI 직접 지정 방식으로 한다.** `ACTION_OPEN_DOCUMENT` + `setPackage("com.android.documentsui")`, `video/*` (7.1에서 에뮬레이터로 확인한 유일한 길).
- **영상 가져오기는 앱에서 따로 떼어 둔다.** 가져오는 부분(가칭 `VideoSource`: 고르기 → `content://` 주소·파일 이름·길이·촬영 시각 후보를 돌려줌)과 그 뒤 흐름(차량 기록 첨부 → 업로드 → 질문 → 결과)을 나눠, 실차 확인 뒤 방법이 바뀌어도(빌트인 캠, 휴대폰 경유 등) 가져오는 부분만 바꾼다.
- 아래 표의 "확인할 것"은 실차 확인 목록이다.

| 방법 | 내용 | 확인할 것 |
|---|---|---|
| (가) 파일 고르기 | Android 저장소 접근 프레임워크(`ACTION_OPEN_DOCUMENT`, `video/*`)로 사용자가 파일을 고름 | 차량 OS(Pleos)에 파일 선택 화면(DocumentsUI)이 있는지, 운전자 사용자(10번)에서 쓸 수 있는지, 주행 중 막히는지(운전 중 제한) |
| (나) USB·SD 카드 | 애프터마켓 블랙박스의 SD 카드를 차량 USB에 꽂아 (가)로 고름 | 차량 USB 저장장치 인식, 블랙박스 SD 카드 파일 시스템(exFAT 등) 지원 |
| (다) 빌트인 캠 | 차량 내장 블랙박스의 녹화 파일을 앱이 직접 읽음 | 내장 캠 파일에 다른 앱이 접근할 API·권한이 있는지 (Pleos Vehicle SDK 2.3.2에 해당 기능이 있는지), 파일 형식·시각 기록. 같은 차량 시계면 5.2의 1번이 됨 |
| (라) 휴대폰 경유 | 블랙박스 Wi-Fi 앱 → 휴대폰 → 서버. 차량 기록은 차량 앱이 따로 올리고 서버가 합침 | 휴대폰 앱이 없음(MTM Flutter 앱은 가져오지 않음, `docs/origin.md`). 두 기기가 같은 사건을 가리키는 방법 |

- 지금 `android/` 앱에는 영상·카메라·파일 고르기 코드가 없다 (`grep` 확인). 업로드 네트워크(차량 LTE·테더링)와 200MB 업로드 시간도 **(확인 필요)**.

### 7.1 USB 저장장치 경로 조사 결과 (2026-11-09, 에뮬레이터)

> 위 표 (나)·(가)를 Pleos 에뮬레이터에서 adb로 확인했다. 코드 수정 없음.
> 환경: AVD `Pleos_Connect_v2.1.0` (Android 14, API 34, `Pleos/crp_avd/…:user/test-keys`, `ro.build.characteristics=nosdcard,automotive`), `-read-only`로 띄워 AVD 상태는 바꾸지 않음. 사용자 0·10 모두 이름이 "운전자"이고, 앞에 떠 있는 사용자는 **10**.
> 실제 USB 메모리는 에뮬레이터에 꽂지 못했다. 대신 **가상 SD 카드**(블록 장치 `vdf`, vfat)로 "차량에 꽂힌 이동식 저장장치"를 흉내 냈다. USB 메모리도 같은 `PUBLIC` 볼륨 경로를 탈 것으로 보지만 **실차 확인이 필요**하다.

**1. 저장소 볼륨 (`sm list-volumes all`, `dumpsys mount`)**

| 볼륨 | 종류 | 상태 | `mountFlags` | 경로 |
|---|---|---|---|---|
| `emulated;0`, `emulated;10` | EMULATED (내장) | mounted | `PRIMARY\|VISIBLE_FOR_WRITE` | `/storage/emulated` |
| `public:253,80` | **PUBLIC (이동식)**, 디스크 `flags=SD` | mounted, `mountUserId=10` | **`0` (VISIBLE 없음)** | `/mnt/media_rw/<UUID>` (**`/storage/<UUID>`에 없음**) |

- **이동식 볼륨 자체는 지원한다.** `vold`가 vfat 카드를 인식해 운전자 사용자(10)에게 마운트한다. AVD 설정이 `hw.sdCard=no`인데도 AVD 폴더의 `sdcard.img`(512MB, 이름 `SDCARD`)가 붙어 있었다.
- **하지만 앱에 "보이는" 볼륨이 아니다.** `mountFlags=0`(VISIBLE 표시 없음)이라 `/storage/` 아래에 폴더가 생기지 않는다(`/storage`에는 `emulated`, `self`만 있음). `adoptable`(내장 저장소로 쓰기)도 없음(`sm has-adoptable` = false).
- 이유(차량용 빌드가 이동식 볼륨을 일부러 숨기는지 등)는 확인하지 못했다.

**2. 에뮬레이터에서 USB/SD를 흉내 내는 법**

| 방법 | 결과 |
|---|---|
| **가상 SD 카드 이미지** (`emulator -avd Pleos_Connect_v2.1.0 -read-only -sdcard <이미지>`) | **됨.** 호스트에서 FAT32 이미지를 만들고(파이썬 `pyfatfs`, 128MB, 이름 `BLACKBOX`) 안에 `Normal/Front/20261109_143012_F.mp4`를 넣어 띄우니, `public:253,80`이 `5D69-5539`(`BLACKBOX`)로 바뀌어 마운트됨. 블랙박스 SD 카드를 가장 비슷하게 흉내 냄. 파일을 바꾸려면 에뮬레이터를 끄고 이미지를 다시 만들어야 함 |
| `adb push`로 SD에 바로 넣기 | **안 됨.** `/mnt/media_rw`는 shell에게 `Permission denied`. user 빌드라 `adb root`도 안 됨 |
| `adb push`로 내장 저장소(사용자 10)에 넣기 | **바로는 안 됨.** `/storage/emulated/10`은 shell에게 `Permission denied` |
| MediaStore로 내장 저장소(사용자 10)에 넣기 (SD 대신) | **됨.** `content insert --user 10 --uri content://media/external_primary/video/media --bind _display_name:s:… --bind relative_path:s:Movies/BlackBox/ --bind mime_type:s:video/mp4`로 행을 만들고 `adb exec-in content write --user 10 --uri content://media/external_primary/video/media/<id> < 파일`로 내용을 씀. MediaProvider가 `duration=3000`, `width`·`height`를 채움. `adb shell … < 파일`은 Windows에서 입력이 깨져 476바이트만 들어갔고, **`adb exec-in`을 써야 함**. SD가 아니라 내장 저장소라 "MediaStore로 고르기"(3절) 시험용 |
| 실제 USB 장치 연결 (`-qemu -device usb-storage` 등) | 시험 안 함 |

**3. 일반 앱이 영상을 읽는 방법별**

| 방법 | 에뮬레이터 결과 | 근거 |
|---|---|---|
| **MediaStore 영상 목록** (`READ_MEDIA_VIDEO`, 일반 런타임 권한) | **SD(이동식) 영상은 안 나옴.** 내장 저장소 영상은 나옴 | 사용자 10의 MediaProvider가 붙인 볼륨이 `internal`, `external_primary`(=`emulated;10`) 둘뿐이고, SD 볼륨을 물으면 `Volume 5d69-5539 not found, … attached volumes: {internal, external_primary}` (logcat). 처음 띄운 SD(`0000-0000`)는 볼륨 이름은 받았지만 행 넣기가 조용히 실패함. SD가 VISIBLE이 아니어서 검색(scan) 대상이 아닌 것으로 봄 |
| **파일 선택 화면 `ACTION_OPEN_DOCUMENT` (그냥 부름)** | **막힘.** | 이 인텐트를 받는 화면이 둘인데, 우선순위가 높은 쪽(101)이 **`com.android.car.frameworkpackagestubs/.Stubs$DocumentsUIStubWithResult`**(차량용 빈 화면)라서 그쪽이 열림. 알림(토스트)만 띄우고 0.8초 만에 닫힘 → 앱은 파일을 못 받음 |
| **`ACTION_OPEN_DOCUMENT` + `setPackage("com.android.documentsui")`** | **됨 (화면까지 확인).** | DocumentsUI(`/system/priv-app/DocumentsUI`)가 설치돼 있음. 패키지를 지정하면 `picker.PickActivity`가 열리고, 왼쪽 목록에 **SD 볼륨(`SDCARD`, `BLACKBOX`)이 보임**. `BLACKBOX > Normal > Front`에 시험 영상(45.73kB)이 영상 아이콘으로 보이고 `video/*` 필터에서 고를 수 있음. VISIBLE이 아닌 볼륨이어도 ExternalStorageProvider가 보여 줌. **고른 뒤 앱이 `content://` 주소를 받아 읽는 것은 시험 앱이 없어 확인 못 함** |
| `ACTION_OPEN_DOCUMENT_TREE` (폴더 통째로) | 그냥 부르면 처리할 화면 없음. `setPackage("com.android.documentsui")`면 `PickActivity`로 풀림 | 폴더를 한 번 허락받아 블랙박스 폴더를 계속 읽는 방식에 쓸 수 있음 (화면은 시험 안 함) |
| `ACTION_GET_CONTENT` | 고르는 창(`CarResolverActivity`)이 뜸: 위 빈 화면, 사진 선택기(MediaStore 기반이라 SD 안 보임), DocumentsUI, 갤러리 중 | 사용자가 DocumentsUI를 골라야 함. 앱이 정할 수 없음 |
| **StorageManager로 볼륨 경로 바로 읽기** (`getStorageVolumes()`, `File`) | **막힘 (추정).** | 볼륨이 VISIBLE이 아니고 `/storage/<UUID>`가 없음. `/mnt/media_rw`는 shell도 못 읽고 일반 앱은 더 막힘. `MANAGE_EXTERNAL_STORAGE`가 있어도 경로가 없으면 소용없음. **앱 코드로 `getStorageVolumes()` 결과를 찍어 확인 필요** (에뮬레이터에 시험 앱 없음) |
| 주행 중 사용 | **주행 중에는 막힐 가능성 큼** | 홈 화면 로그에 DocumentsUI가 `distractionOptimized: false`. 운전 중 제한(UX restriction)이 걸리면 파일 선택 화면이 안 뜰 수 있음. 차가 서 있을 때(P) 고르게 해야 함 |

**4. Pleos 권한·정책**

- 에뮬레이터의 `pleos.car.permission.*` 56개(차량 데이터·제어, 내비, ADAS, TTS·STT·LLM, Wi-Fi 등) 중 **저장소·USB·카메라·영상 관련 권한은 없음**. `ai.pleos.*`·`ai.umos.*` 권한도 미디어 브리지·홈 화면 등 시스템 앱용뿐.
- 저장소 권한은 Android 기본 권한(`READ_MEDIA_VIDEO`, `MANAGE_EXTERNAL_STORAGE` 등)이 그대로 있음.
- Pleos 개발자 문서 (2026-11-09 검색):
  - [vehicle permission](https://document.pleos.ai/en/api-reference/connect-sdk-pleos/Vehicle/vehicle-permission): `pleos.car.permission.CAR_*`(읽기)·`CONTROL_CAR_*`(제어)를 도메인별로 나눔. 권한은 **Pleos App Market과 미리 합의·승인된 범위에서만** 쓸 수 있고, 승인 안 된 권한을 선언하면 앱 심사에서 떨어짐.
  - [Hardware Access Policy](https://document.pleos.ai/en/docs/pleos-only/vehicle-app-planning-guide/platform-api-architecture): 앱이 차량 하드웨어에 직접 접근하지 못하고 SDK·표준 API를 쓰라고 함. 제한될 수 있는 기능 예는 전화·SMS·일부 센서뿐. **USB·이동식 저장소·파일·카메라·블랙박스는 언급 없음.**
  - [SDK API Policy](https://document.pleos.ai/en/docs/pleos-only/vehicle-app-planning-guide/pleos-connect-sdk-api): AAOS 표준 API를 먼저 쓰라고 함. 지원 API는 차종마다 다름.
  - [Security and Privacy](https://document.pleos.ai/en/docs/pleos-only/vehicle-app-planning-guide/security-privacy): 개인정보 최소화·동의, 차량·사용자 id 가명 처리. 저장소·영상 언급 없음. "App Security Guide"는 따로 있다고 함(못 봄).
  - 공개 문서에서 USB 저장장치·블랙박스·빌트인 캠 관련 내용은 찾지 못함.

**정리**

| 구분 | 내용 |
|---|---|
| **가능한 방법** | **DocumentsUI를 패키지로 지정한 파일 선택** (`ACTION_OPEN_DOCUMENT` + `setPackage("com.android.documentsui")`, `video/*`): 이동식 볼륨이 목록에 보이고 영상을 고를 수 있음. 폴더 단위(`OPEN_DOCUMENT_TREE`)도 같은 방식으로 열림. 앱은 받은 `content://` 주소를 `ContentResolver`로 읽어 업로드함 (권한 선언 불필요). 내장 저장소에 있는 영상은 MediaStore(`READ_MEDIA_VIDEO`)로도 목록을 만들 수 있음 |
| **막힌 방법** | 그냥 부른 `ACTION_OPEN_DOCUMENT`(차량용 빈 화면이 가로챔), MediaStore로 이동식 볼륨 영상 목록, `/storage/<UUID>`·`/mnt/media_rw` 경로로 바로 읽기(볼륨이 VISIBLE이 아님). 사진 선택기(`GET_CONTENT`의 한 보기)도 MediaStore 기반이라 이동식 볼륨은 안 보임 |
| **실차에서만 확인 가능한 것** | ① 실제 **USB 메모리**·블랙박스 SD 카드(리더기)를 꽂았을 때 같은 `PUBLIC` 볼륨으로 붙는지, `mountFlags`가 에뮬레이터처럼 0인지, exFAT(대용량 SD 카드에 흔함)을 읽는지. ② 실차 빌드에도 DocumentsUI가 있고 패키지 지정 호출이 막히지 않는지(에뮬레이터는 `test-keys` 빌드). ③ 주행 중 제한: DocumentsUI가 `distractionOptimized: false`라 정차·P단에서만 쓸 수 있는지. ④ Pleos App Market 심사가 `setPackage`로 시스템 화면을 부르는 것과 `READ_MEDIA_VIDEO`를 허용하는지. ⑤ 빌트인 캠 녹화 파일이 이동식·내장 저장소 어디에 있고 다른 앱에 보이는지. ⑥ 차량 USB 포트가 저장장치를 받는지(충전 전용·폰 프로젝션 전용일 수 있음, `android.car.usb.handler`가 있음) |

- 위 결과로 7절 표 (가)·(나)는 "패키지 지정 DocumentsUI로 가능, 실차 확인 필요"로 본다. 앱은 정차 중에만 "블랙박스 영상 고르기" 버튼을 켜고, 그냥 부른 파일 선택이 실패(결과 취소)하면 DocumentsUI 지정 호출로 다시 시도하는 쪽이 안전하다 (Q14 대기, 개발은 이 방식).

## 8. 블랙박스 분석기 출력 명세 (MTM 팀원 공유용)

> 이 절만 떼어 MTM 팀원에게 보낸다. HMTM이 이 출력을 받아 차량 기록과 합치고 질문·판정을 한다. 분석기는 **영상만** 본다.

### 8.1 호출

```python
analyze(video_path: str, recorded_at: dict | None, work_dir: str, progress=None) -> dict
```

- `video_path`: 블랙박스 **앞 카메라** 영상 한 개 (v0는 앞 카메라만. 뒤에서 받힌 사고는 상대가 안 보여도 괜찮습니다: 충격 시각과 `collision.contact: rear` 정도만 주시면 상대는 사용자 질문, 내 차는 차량 기록으로 보강합니다).
- `recorded_at`: `{"start_ms", "source", "tz"}` 또는 `None`. 참고용이고 분석에 쓰지 않아도 됨.
- `work_dir`: 중간 파일을 써도 되는 폴더.
- `progress(n)`: 0~100 진행률 (선택).
- 예외 대신 `status`로 실패를 알려 주세요. 판정 엔진은 부르지 않습니다 (HMTM이 부름).

### 8.2 출력 최상위

| 키 | 필수 | 내용 |
|---|---|---|
| `schema_version` | 예 | `"bb-0.2"` (`"bb-0.1"` 출력도 받음. 8.3.1~8.3.3 항목이 없을 뿐 모양은 같음) |
| `analyzer` | 예 | `{"name", "version"}` |
| `status` | 예 | `ok` / `no_collision` / `unsupported` / `failed` |
| `reason`, `message` | `ok`가 아니면 예 | 코드(예: `not_blackbox`, `video_unreadable`), 한국어 한 문장 |
| `video` | 예 | `{"duration_s", "fps", "frames", "width", "height"}` |
| `facts` | `ok`·`no_collision`이면 예 | FACTS 0.3 모양 (8.3) |
| `ego_motion` | 권장 | 시각 맞추기용 (8.4) |
| `clock` | 선택 | `{"osd_start_ms"}`: 화면 시각 표시를 읽었으면 첫 프레임 시각 (epoch ms) |
| `hints` | 선택 | 질문 참고 자료 (예: `light_hints`). 자유 모양. 단 `collision_candidates`는 `[{"t": 영상 안 초, "frame", "source", "reason"}]` (사고 순간 후보, 앱에 그대로 전달, 3.6) |

### 8.3 `facts`

- `schema_version: "0.3"`. 당사자 id는 **`"ego"`(카메라 차)와 `"other"`(부딪힌 상대)로 고정.**
- **방위 규칙**: 내 차는 늘 남쪽에서 북쪽으로 들어온 것으로 본다. 상대 `entry_from`은 내 차 기준으로 정한다: 왼쪽 길 = `west`, 오른쪽 길 = `east`, 맞은편 = `north`, 같은 방향(내 앞·뒤) = `south`. 화면 방향 벡터(`heading_start`)는 내지 마세요.
- **값 객체**: 판정에 쓰는 값은 모두 `{"value", "source": "model", ...}`로 감쌉니다.

| 상태 | 쓰는 법 |
|---|---|
| 확실함 | `{"value": V, "source": "model", "confidence": 0~1(선택), "evidence_frame": n(선택), "t": 초(선택)}` |
| 추정만 | `{"value": null, "source": "model", "guess": V, "confidence": …}` → HMTM이 질문하고 V를 미리 골라 둠 |
| 봤지만 모름 | `{"value": null, "source": "model", "guess": null}` |
| 지원 안 함 | 키를 넣지 않음 |

- "확실함"의 기준은 분석기 쪽에서 검증으로 정해 주세요. 틀린 확실한 값은 질문 없이 판정에 들어가므로, 애매하면 `guess`로 내는 쪽이 안전합니다.

| 위치 | 항목 | 값 | 필수 |
|---|---|---|---|
| `collision` | `a`, `b` | `"ego"`, `"other"` | 예 |
| | `t`, `frame` | 충돌 순간 (초, 프레임). 못 찾으면 `null` + `status: no_collision` | 예 |
| | `zone` | `intersection` / `road` | 선택 |
| | `contact` | `front` / `left` / `right` / `rear` / `unknown` (내 차가 부딪힌 쪽) | 선택 |
| | `t_confidence` | 0~1. **0.5 미만이면 HMTM이 사고 순간 확인 필요로 보고 차량 기록과 맞추지 않음** (3.6 `collision_review`) | 선택 (권장) |
| | `t_source` | `model` / `guess`. `guess`면 위와 같이 확인 필요 | 선택 |
| `parties.other` | `cls` | `car` `truck` `bus` `two_wheeler` `bicycle` `person` (사고 장을 정함, 8.3.1) | 예 |
| | `movement` | `straight` `left_turn` `right_turn` `u_turn` `lane_change` `reverse` | 예 |
| | `entry_from` | `west` `east` `north` `south` (위 방위 규칙) | 교차로면 예 |
| | `intersection_entry` | `{"frame", "t"}` 교차로에 들어온 순간 | 선택 |
| | `lead_order` | `leading` / `following` (같은 방향일 때) | 선택 |
| | `lane_change_dir` | `left` / `right` | 선택 |
| | `stationary_at_collision` | bool | 선택 |
| | `signal_at_entry`, `turn_signal_used` | FACTS 3-5, 3-4 | 선택 |
| `parties.ego` | `movement` | 위와 같음 | 예 (추정이라도) |
| | `intersection_entry` | `{"frame", "t"}` 내 차가 교차로(정지선)에 들어간 순간 | 선택 (있으면 서행 판정이 정확해짐) |
| | `stationary_at_collision`, `stopped_before_entry` | bool | 선택 |
| | `lane_change_dir` | `left` / `right` | 선택 |
| | `signal_at_entry` | `green` `green_arrow` `yellow` `red` `flashing_red` `flashing_yellow` `none` (내 차 앞 신호) | 선택 |
| | `lane_marking` | FACTS 3-7 | 선택 |
| `road` | `location` | `intersection` / `straight` / `parking_lot` / `roundabout` / `off_road` | 예 (추정이라도) |
| | `junction_type` | `cross` / `t` | 선택 |
| | `signal_present` | bool | 선택 |
| | `center_line` | bool | 선택 |
| | `road_width` | `equal` / `different` (+ 당사자 `on_wider_road`) | 선택 |
| | `night`, `low_visibility` | bool | 선택 |

**내지 않는 것**: `heading_start`, `heading_before_collision`, `approach_speed`, `intersection_entry_speed`, `origin_zone`, `enter_road`, `events[].enter_zone`(고정 화면 기준 값), `speed_kmh` 등 실제 속도(내 차 속도는 차량 기록에서 옴. 상대 실속도는 8.3.3 예외), 내 차 `cls`·`entry_from`(HMTM이 넣음).
사용자 질문으로만 받는 항목(A_REQUESTS "채울 곳 = 질문"만인 것: `crossing_road_width`, `sidewalk_closed`, `expressway_walk_reason`, `vulnerable_type`, 보행 장소의 `arterial_road` 등)도 내지 않아도 됩니다.

#### 8.3.1 상대 종류(`cls`)와 확신도 → 사고 장

판정 엔진은 충돌 당사자의 `cls`로 사고 장을 고릅니다 (`judge/fault_engine.detect_category`). 장이 바뀌면 도표 파일과 질문이 통째로 바뀝니다.

| 분석기 `cls` | 엔진 이름 (`judge/adapter.CLS_MAP`) | 사고 장 (`fault_engine.CATEGORIES`) | 도표 파일 |
|---|---|---|---|
| `car`, `truck`, `bus`, `two_wheeler` | 같음 | `car_car` 차대차(이륜차 포함) | `rules.json` |
| `person` | `person` (`PEDESTRIAN_CLS`) | `car_pedestrian` 차대보행자 | `rules_pedestrian.json` |
| `bicycle` | `bicycle` (`BICYCLE_CLS`) | `car_bicycle` 차대자전거(농기계 포함) | `rules_bicycle.json` |

- **보행자는 `person`으로 내 주세요.** `pedestrian`도 엔진이 `person`으로 바꾸지만, 계약은 `person` 하나입니다. 농기계(`farm_machine`)는 분석기 값에 없습니다 (사용자 답으로만).
- 분석기가 장 이름(`car_pedestrian` 등)이나 `facts.accident_category`를 따로 낼 필요는 없습니다. HMTM·엔진이 `cls`에서 정합니다.
- **확신도**: `cls` 값 객체의 `confidence`(0~1)를 꼭 넣어 주세요 (다른 항목은 선택). 계약 시험 `Output.test_cls_has_confidence`가 bb-0.2 출력(`ok`, 그리고 `cls`를 낸 `no_collision`)에서 이것을 확인한다. 장을 가르는 값이라 틀리면 질문·도표가 모두 엇나갑니다.
  - 확실함: `{"value": "person", "source": "model", "confidence": 0.93, "evidence_frame": 412}`
  - 추정만: `{"value": null, "source": "model", "guess": "person", "confidence": 0.55}` → HMTM이 "상대는 무엇이었나요?"를 **맨 앞에** 묻고, 답이 오면 장을 다시 고릅니다 (2.4 순서 4).
  - 판정 엔진은 `cls`가 비어 있으면 **차대차로 판정**합니다("차종 정보가 없어 차대차로 판정"). 그래서 보행자·자전거일 수 있는데 확실하지 않으면 `guess`를 꼭 채워 주세요 (HMTM이 임시 판정에 `guess`를 넣음).
- 선택: 종류별 점수를 `hints.cls_scores`에 줄 수 있습니다: `{"car": 0.05, "two_wheeler": 0.30, "bicycle": 0.60, "person": 0.05}` (키는 `cls` 값, 합 1일 필요 없음). 이륜차·자전거처럼 장이 갈리는 두 후보가 비슷할 때 질문 보기 순서에 씁니다.

#### 8.3.2 보행자·자전거: 도표 선택용 항목

`backend/judge/docs/A_REQUESTS.md`(hmtm-0.1.1, 2026-11-10) "1. 도표 선택용"에서 **채울 곳에 영상·모델이 있는 항목**입니다. 비어 있으면 그 도표가 판단 보류라 비율 자체가 안 나옵니다. 이름·값은 판정 엔진 이름 그대로입니다(A 질문 이름 `crossing_place`·`ped_signal_at_crossing`이 아님). 위치는 판정 엔진이 읽는 곳(`judge/adapter.py`의 `OPTIONAL_PARTY_FIELDS` = 당사자, `SCENE_FIELDS` = `road`)입니다.

**차대보행자** (`other.cls = person`)

| 위치 | 항목 | 값 | 갈리는 도표 | A_REQUESTS 채울 곳 |
|---|---|---|---|---|
| `parties.other` | `ped_place` | `crosswalk` `near_crosswalk` `near_overpass` `intersection` `road` `sidewalk` `roadway` `ped_only_road` `ped_priority_road` (FACTS 3-15) | 보1~보29 | 모델 + 질문 |
| `parties.other` | `dist_from_crosswalk_m` | m (아래 4구간) | 보14~보23, 수정요소 `ped_near_10_30m` | 모델 + 질문 |
| `parties.other` | `ped_signal_at_start`, `ped_signal_at_impact` | `green` `flashing_green` `red` (건너기 시작할 때 / 부딪힐 때 보행자 신호) | 보1~보12, 보14~보19 | 모델 + 질문 |
| `parties.other` | `ped_activity` | `crossing` `walking` `lying_or_playing` | 보23, 보27-1·보27-2·보28, 보30 | 영상 (누움은 모델) + 질문 |
| `parties.other` | `roadway_walk_position` | `edge_1m` `beyond_1m` `edge` `center` | 보26, 보27-2, 보28 | 모델 + 질문 |
| `parties.ego` | `impact_after_intersection` | bool (교차로를 지난 뒤 부딪힘) | 보1~보7 vs 보8~보12 | 영상 |
| `parties.ego` | `passed_crosswalk` | bool (횡단보도를 지난 뒤 부딪힘) | 보14~보18 vs 보19 | 모델 |
| `parties.ego` | `right_turn_signal` | `green` `red` `none` (우회전 신호기) | 보17, 보18 | 모델 + 질문 |
| `parties.ego` | `riding_on_crosswalk` | bool (이륜차가 횡단보도를 타고 건넘. 내 차가 이륜차일 때만) | 보33 | 모델 + 질문 |
| `road` | `crosswalk_signal` | bool (그 횡단보도에 보행자 신호기가 있나) | 보1~보19 vs 보13·보20 | 모델 + 질문 |
| `road` | `sidewalk_separated` | bool (보도·차도 구분) | 보25·보26 vs 보27-1~보28 | 모델 + 질문 |

- `ped_signal_at_crossing`(차53-1)은 내지 않습니다. HMTM이 `ped_signal_at_impact`와 같은 값으로 넣습니다 (A_REQUESTS 요청 1).
- 보행자 신호는 블랙박스에 잘 안 보이는 경우가 많습니다. 확실하지 않으면 `guess`로.

**횡단보도 거리 4구간** (A_REQUESTS "횡단보도 거리는 도표가 4구간을 쓴다")

| 구간 | `ped_place` | `dist_from_crosswalk_m` | 적용 |
|---|---|---|---|
| 횡단보도 위 | `crosswalk` | 내지 않음 | 보1~보13 |
| 10m 이내 | `near_crosswalk` (육교·지하도는 `near_overpass`) | 잰 값, 못 재면 대표값 **5** | 보14~보21 |
| 10~30m | `near_crosswalk` / `near_overpass` | 잰 값, 못 재면 대표값 **20** | 같은 도표 + `ped_near_10_30m` (보행자 +10) |
| 30m 초과 | `near_crosswalk` / `near_overpass` | 잰 값, 못 재면 대표값 **40** | 무단횡단 기준 보22(교차로)·보23(단일로) |

- 값 객체에 구간 이름 `bin`(`within_10m` / `10_30m` / `over_30m`)과 잰 값인지 `measured`(bool)를 같이 넣어 주세요. 엔진은 `value`만 읽고 나머지 키는 무시합니다.
  예: `{"value": 20, "source": "model", "bin": "10_30m", "measured": false, "confidence": 0.7}`
- 구간 경계는 엔진 조건대로 **10 < 거리 ≤ 30**이 10~30m, **≤ 10**이 10m 이내, **> 30**이 30m 초과입니다.
- 구간이 애매하면(예: 10m 근처) `value: null` + `guess`(대표값) + `bin`으로. 횡단보도가 화면에 아예 없으면 `ped_place`를 `intersection`/`road`(모델 추정) 또는 비워 두고 거리도 내지 않습니다 (추측하지 않음).

**차대자전거** (`other.cls = bicycle`)

| 위치 | 항목 | 값 | 갈리는 도표 | A_REQUESTS 채울 곳 |
|---|---|---|---|---|
| `parties.other` | `crossing_road` | bool (자전거가 도로를 가로질러 건넘) | 거41, 거33-2와 구분 | 영상 + 질문 |
| `parties.other` | `on_bike_crossing` | bool (자전거횡단도 위) | 거42 | 모델 (횡단도 영역) + 질문 |
| `parties.other` | `bike_lane_type` | `dedicated_road` `dedicated_lane` `priority_road` `none` | 거43 | 질문 (모델 가능) |
| 당사자별 | `approached_right_edge` | bool (우회전 전 오른쪽 끝으로 다가섬) | 거10 | 영상 + 질문 |

- `stop_sign`, `unprotected_left_sign`, `one_way_violation`, `wrong_way`, `from_off_road`는 A_REQUESTS에서 질문 전용이라 내지 않아도 됩니다.

#### 8.3.3 보행자·자전거: 수정요소 전용 항목 (선택)

A_REQUESTS "2. 수정요소 전용"에서 채울 곳에 영상·모델이 있는 항목입니다. 비어 있으면 그 가감만 "확인 필요"로 남고 기본 비율은 나옵니다. 위치는 도표가 가감을 거는 당사자입니다 (보행자·자전거 쪽이면 `parties.other`).

| 장 | 위치 | 항목 | 값 | A_REQUESTS 채울 곳 |
|---|---|---|---|---|
| 보행자 | `parties.other` | `ped_factors` | `group` `sudden_entry` `intentional_block` `inline_skate` 중 해당 값 배열 (없으면 `[]`) | 영상 + 모델 + 질문 |
| 보행자 | `parties.other` | `walk_manner` | `normal` `stop` `back` `zigzag` | 영상 |
| 보행자 | `parties.other` | `diagonal_crossing` | bool | 영상 |
| 보행자 | `parties.other` | `opposite_side_start` | bool | 영상 |
| 보행자 | `parties.other` | `inside_stop_line` | bool (정지선 안쪽에서 건넘) | 모델 (정지선 영역) |
| 보행자 | `parties.other` | `passed_stopped_vehicles` | bool | 영상 |
| 보행자 | `parties.other` | `ped_posture` | `sitting` `lying` `standing` | 모델 |
| 보행자 | `parties.other` | `on_shoulder` | bool (고속도로 갓길) | 모델 + 질문 |
| 보행자 | `parties.other` | `behind_before_reverse` | bool (후진 전부터 차 뒤에 있었음, 보32) | 영상 |
| 보행자 | `road` | `crossing_prohibition` | `none` `sign` `barrier` | 모델 + 질문 |
| 보행자 | `road` | `protection_zone` | `child` `elderly` `disabled` `none` | 질문 (표지 인식은 모델) |
| 보행자 | `road` | `bad_weather` | bool | 질문 (악천후는 모델 가능) |
| 자전거 | `parties.other` | `bike_lane_nearby`, `in_bike_lane` | bool | 모델 + 질문 |
| 자전거 | `parties.other` | `left_side_riding` | bool (도로 왼쪽 통행) | 영상 |
| 자전거 | `parties.other` | `diagonal_crossing` | bool | 영상 |
| 자전거 | `parties.other` | `path_blocked`, `obstacle_ahead` | bool | 모델 + 질문 |
| 자전거 | `parties.other` | `user_factors`의 `no_helmet` | 목록에 넣음 | 질문 (`no_helmet`은 모델 가능) |
| 자전거 | 당사자별 | `off_right_side` | bool (오른쪽 통행 불이행) | 영상 + 질문 |
| 자전거 | `parties.other` | `intersection_entry_speed_kmh` | km/h. 실속도를 잴 수 있을 때만 (HMTM이 제한속도로 `entry_speed_to_limit`을 계산) | 영상 (실속도 필요) |
| 자전거 | `road` | `lanes_two_plus`, `dashed_bike_lane_border` | bool | 모델 + 질문 |

- 값 목록이 FACTS 3-15·3-16에 있는 항목은 그 이름 그대로 써 주세요. 보행자 `reverse_warning`, 운전자 사정(`user_factors` 자동차 쪽), `speed_over_limit_kmh`는 질문·차량 기록이라 내지 않습니다.
- `night`는 이미 `road.night`(8.3 표)로 받습니다.

### 8.4 `ego_motion`

```json
{"fps": 30.0, "step": 3, "t": [0.0, 0.1, …], "speed_proxy": […], "moving": […], "yaw_proxy": […], "jolt_t": [13.9]}
```

- `t`: 영상 처음 기준 초. 0.1초 안팎 간격.
- `speed_proxy`: 단위 없는 속도 대리 값 (예: `ego_motion.py`의 `mag`). 차량 속도 기록과 모양을 맞춰 시계 차이를 찾는 데 씁니다.
- `moving`: 달리는 중인지. `yaw_proxy`: 좌우 회전 대리 값(예: `tx`). `jolt_t`: 충격 후보 시각.
- 판정에는 쓰지 않습니다. 없으면 시각 맞추기가 파일 이름 시각과 충돌 시각만으로 거칠게 됩니다.

### 8.5 지금 실험 코드와의 대응

| 실험 | 채우는 곳 |
|---|---|
| `ego_motion.py` | `ego_motion` 전체, `collision.t` 후보(`jolt_frames`), `parties.ego.movement` 추정(`yaw_total_px`), `ego.stationary_at_collision`·`stopped_before_entry`(달림·멈춤 구간) |
| `lead_vehicle.py` | 추돌일 때 `other` 고르기, `other.lead_order: leading`, `other.entry_from: south`, 충돌 확인 |
| `bb_signal.py` | `road.signal_present`(`guess`), `parties.ego.signal_at_entry`(지금 `ego.signal_color` → 이름 바꿈. `etc`는 하나로 못 정하니 `guess: null`), `hints.light_hints` |
| (아직 없음) | `other.movement`·`entry_from`(옆·맞은편 상대), `road.location`·`junction_type`, `intersection_entry`, 차선·노면표시. **맡을 범위는 상의 중**입니다. 못 하는 항목은 키를 넣지 않으면 HMTM이 사용자에게 묻습니다 |

### 8.6 HMTM이 시험하는 것

- 출력 모양 검사(필수 키, 값 범위, 당사자 id). 틀리면 사건이 `failed`(`analyzer_output_invalid`)가 됩니다.
- 판정 엔진 변환기(`judge/adapter.to_engine_facts`)가 `facts`를 오류 없이 읽는지.
- 시나리오 영상 몇 개의 예상 결과. 짧은 샘플 영상과 예상 `facts`를 함께 주시면 계약 시험에 넣겠습니다.

## 9. 결정 사항

v0.1(2026-11-09)에서 확정했다. **대기**는 기본안으로 개발을 진행하면서 상의·실차 확인을 기다리는 것이다.

### 9.1 결정 표

| # | 결정할 것 | 이 문서의 제안 | 다른 선택지 | **확정** |
|---|---|---|---|---|
| Q1 | 분석기 출력 모양: FACTS 0.3 그대로 + 블랙박스 블록(`bb-0.1`) | 제안대로 (1.2, 8절) | 블랙박스 전용 새 모양을 두고 HMTM이 FACTS로 변환 | **제안대로** (1.2, 8절) |
| Q2 | MTM 팀원과 범위 나누기: 상대 `movement`·`entry_from`, 장소 분류, 진입 시각을 MTM이 하는지 | MTM이 영상 쪽 전부 (8.5 "아직 없음" 줄) | 일부는 HMTM이 질문으로만 받음 | **대기 (팀원 상의).** 기본은 제안대로. MTM 분석기가 못 내는 항목은 사용자 질문으로 받음 (1.5, 8.5) |
| Q3 | `/api/vehicle-cases` | 테스트·데모용으로 둠, 앱에서는 숨김 (6절 가) | 새 흐름으로 합침 / 지움 | **제안대로** (6절) |
| Q4 | 공통 코드 위치 | v0는 `src/blackbox/`가 `src/vehicle/`을 불러 씀. 둘 다 쓰는 코드가 커지면 `src/hmtm_core/`(가칭)로 옮김 | 처음부터 옮김 | **제안대로** (3.5) |
| Q5 | 주소·이름 | `/api/bb-cases`, 표 `bb_cases`, 오류 `bb_case_not_found` | `/api/hmtm-cases`, `/api/incidents` 등 | **제안대로** (3.2) |
| Q6 | 오래 걸리는 분석을 돌릴 곳 | v0(가짜) = API 프로세스 안 스레드, 진짜 분석기 때 HMTM 작업자 프로세스 (3.4) | 처음부터 작업자 | **제안대로** (3.4) |
| Q7 | 충돌 기록 칸 | `source_conflicts` 새 칸 + `answer_conflicts`는 지금 뜻대로 둠 (4.3) | `answer_conflicts` 하나를 넓힘 | **제안대로** (4.3) |
| Q8 | 뒤 카메라 | v0는 앞 카메라만 | 뒤 카메라도 받아 뒤에서 받힌 사고 | **v0는 앞 카메라만.** 뒤에서 받힌 사고는 차량 기록(정지·제동)으로 내 차 쪽을 보강하고 상대는 질문 (1.1). 뒤 카메라는 **보류** (9.2) |
| Q9 | 우선순위 예외 | `user > vehicle > video > default`, 시각 맞추기가 거칠면 시각에 기대는 차량 값은 안 씀, 추정값끼리 다르면 미리 고르지 않음 (4.2) | 항목별 표로 따로 정함 | **제안대로** (4.2) |
| Q10 | 영상의 내 차 진입 시각이 있을 때 서행 규칙 | v0는 지금 규칙(`slowed_v0`, 진입 1.5~3초 전 가정) 그대로. 진입 시각을 쓰는 `slowed_v1`은 진짜 분석기가 그 값을 낼 때 | 바로 v1 | **제안대로** (3.5) |
| Q11 | 시각 맞추기 등급 기준(상관 0.7·0.4, 0.5초)과 사용자 확인 화면 | 임시값으로 두고 실차 영상으로 조정 (5.3) | | **제안대로** (5.3) |
| Q12 | 차량 기록 구간 길이 제한 | 블랙박스 사건은 `영상 길이 + 30초`, 최대 300초 (5.5) | 120초 그대로 (긴 영상은 앱이 자름) | **제안대로** (3.5, 5.5) |
| Q13 | 영상 보관 | 판정이 끝나도 사건을 지울 때까지 보관. 자동 삭제 기간은 영상 사건처럼 7일? | 분석 뒤 영상 바로 삭제(결과·`bb_facts`만 남김) | **분석이 끝나면 원본 영상 삭제.** `bb_facts`와 판정만 남김. 개발 모드에서만 `HMTM_KEEP_VIDEO=1`로 보관 (3.2, 3.3). **예외 (2026-11-12)**: 사고 순간이 없거나 불확실하면 사용자가 고를 때까지 최대 7일 보관 (3.2) |
| Q14 | 영상 가져오기 방법 | 에뮬레이터 결과(7.1)로는 **DocumentsUI를 패키지로 지정한 파일 선택**이 유일하게 통하는 길. 실차에서 USB·SD 인식, 주행 중 제한, 앱 심사 허용을 확인한 뒤 정함 | 빌트인 캠 연동, 휴대폰 경유 (7절 다·라) | **대기 (실차 확인).** 개발은 USB + DocumentsUI 직접 지정 방식. 앱에서 영상 가져오기 부분을 분리 (7절) |
| Q15 | 확실한 영상 값의 "입증 필요" | 붙이지 않음 (`model`, 판정 엔진 그대로, D6와 같은 이치) | 영상 값도 "영상 제출 필요" 표시 | **제안대로** (4.1) |
| Q16 | 가짜 분석기 시나리오 고르기 | 요청 `scenario` 칸 > 파일 이름 `__scn-` > 기본값 (2.1) | 칸 하나만 | **제안대로** (2.1) |
| Q17 | CLAUDE.md "1차 범위: 비신호 교차로 CCTV" 문장 | MTM에서 옮긴 backend 규칙이라 두되, HMTM 범위는 블랙박스라는 줄을 공통 절에 더할지 | | **CLAUDE.md 공통 규칙에 "HMTM의 범위는 블랙박스 영상"을 더하고, backend 규칙의 CCTV 범위 문장에 "MTM 엔진의 원래 범위"라는 설명을 더함** (반영함) |
| Q18 | 차량 기록을 판정에 넣는 방법 (2026-11-10) | 차량 기록은 참고 자료: 판정은 영상·사용자 답, 차량 기록을 더한 판정과 차이를 따로 보여 줌 (4.4) | D6대로 입증된 값으로 바로 반영 | **제안대로** (4.4). D6을 바꿈. 제출·내보내기는 만들지 않음 |

### 9.2 보류·대기 항목

| 항목 | 상태 | 다시 볼 때 |
|---|---|---|
| 뒤 카메라 영상 (Q8) | **보류.** v0는 앞 카메라만 | 뒤에서 받힌 사고를 질문·차량 기록만으로 처리했을 때 부족한 점이 쌓이면. 받게 되면 분석기 입력이 영상 두 개가 되고, 두 영상의 시각 맞추기가 더 필요함 |
| MTM 분석기 범위 (Q2) | **대기 (팀원 상의)** | MTM 팀원이 8절을 보고 맡을 항목을 정하면. 못 맡는 항목은 지금처럼 질문 |
| 영상 가져오기 방법 (Q14) | **대기 (실차 확인)** | 7.1 "실차에서만 확인 가능한 것" ①~⑥을 확인하면. 앱의 가져오기 부분만 바꿈 |
