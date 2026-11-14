# 백엔드 설계 (초안)

> 2026-10-26 · 담당: A(백엔드), B(프론트) · 앱과 주고받는 데이터 모양은 `docs/app_io.md`, 이 문서는 그걸 웹 API로 감싸는 방법. 로그인·보관함·투표까지 앱 전체 흐름과 데이터 표는 `docs/app_flow.md` (10-29)

## 1. 지금 있는 것과 숫자

`run_app.py`가 이미 백엔드가 할 일을 거의 다 한다: 영상 → 카메라 확인 → (흔들림 보정) → 탐지·추적 → 충돌 → 영역 → 사실 → B 판정 → `app.json`. 백엔드는 이걸 **서버에서 여러 사용자 요청을 받아 돌리는 형태**로 바꾸는 일이다.

평가 24개(10초 영상, GPU 없는 18코어 CPU)로 잰 시간:

| 단계 | 처음 분석 | 답 넣고 다시 판정 |
|---|---|---|
| 카메라 확인 | 1초 | - |
| 흔들림 보정 (흔들리는 영상만) | 13초 | - |
| **탐지·추적 (YOLO)** | **26초 (최대 48초)** | 다시 안 함 |
| 직접 표시한 당사자 추적 | - | 1초 (표시했을 때만) |
| 나머지 (충돌~판정) | 1초 미만 | 0.1초 미만 |
| 질문 그림 그리기, 도로 폭·중앙선 경우별 판정 | 1~2초 | 1~2초 |
| 라이브러리 불러오기 (torch, YOLO) | 2.3초 | 2.3초 |
| **합** | **약 30~60초** | **약 4초** |

답 반영 4초 중 절반이 매번 라이브러리를 새로 불러오는 시간이다. 서버에서는 작업자가 미리 불러 두므로 1~2초로 준다.

- 탐지가 거의 전부다. 영상 길이에 비례해서 1분짜리 영상이면 2~5분이 걸린다
- 탐지에는 교차로 모서리가 필요 없다. 모서리는 영역·진입 단계부터 쓴다
- 그래서 **업로드하자마자 탐지를 시작하고, 사용자가 모서리를 찍는 동안 뒤에서 돌린다.** 모서리를 다 찍을 즈음 탐지가 끝나 있으면 사용자는 거의 기다리지 않는다
- 결과 폴더는 사건 하나에 1~2MB (보정 영상이 있으면 +5~15MB)

## 2. 사용자 흐름과 서버가 하는 일

와이어프레임 순서에 맞춘 흐름이다.

```
[앱]                                   [서버]
1. 영상 종류 고르기 (CCTV / 블랙박스)
2. 영상 올리기 ───────────────────▶  사건 만들기. 블랙박스면 바로 unsupported
                                      준비 작업 시작 (뒤에서):
                                        카메라 확인 → 달리는 블랙박스면 unsupported
                                        흔들리면 보정
                                        모서리 찍기용 배경 그림
                                        탐지·추적 (YOLO, 가장 오래 걸림)
3. 배경 그림에 교차로 모서리 찍기 ◀──  배경 그림 (보정 영상이면 보정된 그림)
   (삼거리면 길 없는 쪽)
4. 모서리 보내기 ─────────────────▶  장면 만들고 검사 (네 점이 몰렸는지 등). 장면 그림 돌려줌
5. "분석 중" 화면 ◀───────────────▶  탐지가 끝났으면 바로, 아니면 끝나는 대로
                                      나머지 단계 → app.json
6. 질문 화면 / 결과 화면 ◀────────── app.json (그림 주소 포함)
7. 답 보내기 ─────────────────────▶  다시 판정 (1~2초) → app.json
   (6~7 반복, done이면 결과 화면)
```

## 3. API

모두 JSON. 사건 id는 추측할 수 없는 UUID. 오류는 `{"error": "<코드>", "message": "<사용자에게 보여 줄 한국어>"}`.
**로그인(아래 "로그인·회원")을 빼고 모든 주소에 `Authorization: Bearer <access>`가 필요하다** (그림 주소 포함). 남의 사건·없는 사건은 똑같이 `404`.

### 로그인·회원 (10-29)

| 메서드·주소 | 하는 일 | 응답 |
|---|---|---|
| `POST /api/auth/kakao` · `/google` | 앱 SDK가 받은 토큰 `{"token": 카카오 access token / 구글 ID token}` | `{"access", "refresh", "access_expires_in", "user"}`. `user.needs_signup`이면 가입 화면 |
| `POST /api/auth/dev` | 개발용 (`MTM_DEV_LOGIN=1`일 때만) `{"token": "아무 이름"}` | 위와 같음 |
| `PUT /api/me` | 가입·정보 고치기 `{"nickname", "agree_terms": true, "train_consent"}` (닉네임 2~12자, 중복 `409`) | 회원 |
| `GET /api/me` | 내 정보 | `{"id", "provider", "nickname", "needs_signup", "train_consent"}` |
| `POST /api/token/refresh` | `{"refresh"}` → 새 토큰 두 개. 쓴 refresh는 다시 못 씀 | 로그인과 같음 (`user` 없음) |
| `POST /api/token/logout` | `{"refresh"}` 지우기 | `204` |
| `DELETE /api/me` | 탈퇴: 사건·글·투표·신고·로그인 기록 모두 삭제 | `204` |

가입(닉네임 + 약관)이 안 끝났으면 `/api/me` 말고는 `403 signup_required`. access가 만료되면 `401 token_expired` → refresh로 새로 받는다.

### 분석

| 메서드·주소 | 하는 일 | 응답 |
|---|---|---|
| `POST /api/cases` | 영상 올리기 (`multipart`: `video`, `source`=`cctv`·`blackbox`) | `201` 사건. 준비 작업이 바로 시작됨 |
| `GET /api/cases/{id}` | 사건 상태 (앱이 몇 초마다 물어봄) | 상태, 진행 단계, 결과가 있으면 결과 |
| `GET /api/cases/{id}/background.jpg` | 모서리 찍을 그림 (지나가는 차를 지운 배경) | 그림. 준비가 덜 됐으면 `409` |
| `GET /api/cases/{id}/frames/{n}.jpg` | 영상의 n번째 장면 (모서리 찍기 슬라이더, 직접 표시) | 그림 |
| `PUT /api/cases/{id}/scene` | 모서리 보내기 `{"corners": [[x,y]×4], "closed": null, "frame_ref": 0, "place": "intersection"}` (`place`: 교차로 / `roundabout` / `parking_lot` / `straight`) | 장면 그림 주소. 잘못되면 `422` |
| `PUT /api/cases/{id}/answers` | 지금까지의 답 전부 (`app_io.md` 2.2, 2.3) | `202`. 결과는 `GET /api/cases/{id}`로 |
| `GET /api/cases/{id}/files/{path}` | 질문 그림 등 결과 파일 | 그림 |
| `GET /api/cases/{id}/evidence` | 근거 화면 (11-03): 두 당사자 궤적 박스와 사건 기록. 판정 전이면 `409 not_ready` | `{"duration", "fps", "width", "height", "aspect", "collision_t", "collision_frame", "tracks": [{"id", "role": "a"·"b", "cls", "frames": [{"t", "box": [x, y, w, h]}]}], "events": [{"t", "type": appear·enter·stop·collision, "track", "text"}]}`. 좌표는 화면 비율(0~1), 시간은 초. 원본 영상은 안 줌 (앱이 휴대폰의 원본 위에 그림) |
| `DELETE /api/cases/{id}` | 사건과 영상 지우기 (투표글도 같이) | `204` |
| `PUT /api/cases/{id}/save` | 보관함 저장 `{"saved": true}` / 취소. 저장 안 한 사건은 `delete_at`(7일 뒤)에 자동 삭제 | 사건 (결과 빼고). 투표에 올린 사건은 취소 못 함 `409 has_post` |
| `GET /api/me/cases` | 내 분석 기록 (최근 것부터) | 사건 목록 (결과 빼고). 판정이 있으면 `summary: {"rule_id", "title", "fault_by_track", "provisional", "track_order", "status"}` (11-03, status는 11-04). `status`는 판정 상태(ok, no_rule 등). `track_order`는 당사자 순서(근거 화면 파랑·주황 순서)로, 비율은 이 순서로 보여 줌 |

### 투표 (10-29, `app_flow.md` 4절)

| 메서드·주소 | 하는 일 | 응답 |
|---|---|---|
| `POST /api/posts` | 글쓰기 `{"case_id", "title", "body", "visibility": "frames"}`. 저장한 `done` 사건만, 사건 하나에 글 하나. 올릴 때 결과·사고 설명을 스냅샷으로 저장 | 글 |
| `GET /api/posts?before=&limit=` | 목록 (최근 것부터, 다음 쪽은 마지막 글의 `created_at`을 `before`로) | `[{"id", "title", "author", "created_at", "vote_count", "thumbnail"}]` |
| `GET /api/posts/{id}` | 글. 당사자는 A(충돌 그림 빨강)·B(파랑). **`ai`(AI 결과)와 `votes`(평균·분포)는 투표한 사람과 글쓴이에게만** | 글 |
| `PUT /api/posts/{id}/vote` | `{"a_ratio": A의 과실 0~100, 10 단위}`. 다시 보내면 바꿈. 글쓴이는 `403` | 글 (`ai`, `votes` 포함) |
| `POST /api/posts/{id}/report` | 신고 `{"reason"}` (한 사람 한 번). 3번이면 숨김 | `204` |
| `DELETE /api/posts/{id}` | 글쓴이가 지움 (분석 기록은 남음) | `204` |
| `GET /api/me/posts` | 내 글 (숨김 여부 `status` 포함) | 목록 |
| `GET /api/posts/{id}/files/{name}` | 글 그림 (`collision.jpg`, `path_A.jpg`, `path_B.jpg`) | 그림 |

글 응답: `{"id", "title", "body", "author", "is_author", "created_at", "place", "signal_present", "collision_t", "collision_image", "parties": {"A": {"cls", "movement", "entry_from", "path_image"}, "B": …}, "my_vote", "vote_count", "ai"?: {"rule_id", "fault": {"A", "B"}, "applied_modifiers", "provisional"}, "votes"?: {"count", "a_avg", "distribution": {"0": n, "10": n, …}}}`

`GET /api/cases/{id}` 응답 예:

```json
{"id": "6f1c…", "status": "needs_answers",
 "stage": null,
 "result": { …app.json 그대로, 그림 경로는 /api/cases/{id}/files/… 주소로 바꿈… },
 "created_at": "2026-10-26T10:00:00+09:00"}
```

### 사건 상태

| `status` | 뜻 | 앱 화면 |
|---|---|---|
| `preparing` | 카메라 확인·보정·탐지 중 (`stage`에 단계 이름) | 모서리 찍기 화면은 배경 그림이 나오면 바로 열 수 있음 |
| `waiting_scene` | 준비는 끝났고 모서리를 기다림 | 모서리 찍기 |
| `analyzing` | 모서리를 받아 나머지 단계를 도는 중 (또는 탐지가 아직 안 끝남) | 분석 중 |
| `needs_answers`, `done`, `no_collision`, `unsupported` | `app_io.md` 3.1과 같음 | 질문 / 결과 / 다시 고르기 / 안내 |
| `failed` | 서버 오류 (파이썬 오류). `message`에 안내 | "다시 시도해 주세요" |

모서리와 탐지는 순서가 정해져 있지 않다. 모서리가 먼저 오면 `analyzing`으로 두고 탐지가 끝나는 대로 이어서 돌린다.

## 4. 구조

```
앱 ──HTTP──▶ API 서버 (FastAPI) ──▶ SQLite (사건·작업 표)
                  │                      ▲
                  └─ 영상·결과 파일 ──▶ 디스크 cases/<id>/
                                         ▲
               작업자 (worker, 1개~) ────┘  YOLO·판정 모듈을 한 번 불러 두고 작업을 차례로 처리
```

- **API 서버와 작업자를 나눈다.** 탐지는 수십 초 걸리고 CPU를 다 쓴다. 요청을 받는 서버가 직접 돌리면 그동안 다른 요청을 못 받는다
- **작업 줄은 SQLite 표 하나로 시작한다** (`jobs`: 사건, 종류, 상태, 만든 시각). 작업자가 비는 대로 가져간다. Redis나 Celery 같은 서버를 따로 두지 않아도 되고, 사용자가 늘면 그때 바꾼다
- 작업 종류는 셋: `prepare`(카메라·보정·배경·탐지), `solve`(모서리 이후 나머지), `answer`(답 넣고 다시 판정)
- **작업자는 모델을 한 번만 불러 둔다.** 지금 `run_app.py`는 실행할 때마다 torch·YOLO를 새로 불러서, 0.1초면 끝나는 답 판정에 2.3초가 더 붙는다
- 한 사건의 작업은 한 번에 하나만 (같은 폴더를 동시에 고치지 않게). 답을 빨리 여러 번 보내면 마지막 것만 돌린다

### 저장

```
cases/<id>/
  video.mp4            올린 영상
  stabilized.mp4       흔들림 보정 (흔들린 영상만)
  background.jpg       모서리 찍기용
  scene.json, tracks.json, tracks_final.json, …   지금 결과 폴더와 같음
  answers.json, app.json
  frames/              질문 그림
```

지금의 결과 폴더 구조를 그대로 쓴다. 파이프라인 코드는 폴더만 받으면 되도록 이미 짜여 있다.

## 5. 파이프라인 코드에서 바꿀 것

1. **`run_app.py`를 라이브러리로 나누기** (`src/app/pipeline.py`)
   - `prepare(case_dir, video, source)`: 카메라 확인, 보정, 배경 그림, 탐지
   - `set_scene(case_dir, corners, closed, frame_ref)`: 장면 만들고 검사, 장면 그림
   - `solve(case_dir, answers)`: 나머지 단계와 판정 → `app.json`
   - `run_app.py`는 이 셋을 차례로 부르는 명령으로 남긴다 (평가 도구·시험이 그대로 돌게)
2. **오류를 `SystemExit` 대신 예외로**: `InputError(code, message)`(사용자 잘못, `422`)와 그 밖의 오류(`failed`)를 나눈다. 지금 한국어 안내 문구는 그대로 `message`로 쓴다
3. **배경 그림 만들기**를 `tools/pick_corners.py`에서 `src/app/`로 옮김 (프레임 15장의 중앙값)
4. **탐지 진행률**: 탐지 단계에서 몇 프레임째인지 남기면 "분석 중 40%"를 보여 줄 수 있다

### pipeline.py (10-27)

| 함수 | 하는 일 | 오류 |
|---|---|---|
| `prepare(case_dir, video, source, name)` | 블랙박스 선택이면 바로 `"unsupported"`. 아니면 영상 읽기 확인 → 카메라 확인 → 흔들리면 보정(달리는 카메라면 `"unsupported"`) → `background.jpg` → 탐지. 이미 탐지했으면 건너뜀. 반환 `"ready"` / `"unsupported"` (이유는 `app.json`) | `video_unreadable` |
| `set_scene(case_dir, video, corners, closed, frame_ref, place)` | 장소 종류(기본 교차로) + 모서리 `[[x, y]×4]` 검사 → `scene.json`, `scene.jpg`. 탐지 전이든 후든 됨. 삼거리(`closed`)는 교차로에서만 | `corners_invalid`, `corners_count`, `corners_range`, `corners_too_close`, `closed_invalid`, `place_invalid`, `video_unreadable` |
| `solve(case_dir, video, answers, judge_dir, name)` | 나머지 단계 → 판정 → `app.json`을 저장하고 돌려줌 | `scene_missing`, `not_prepared`, `answers_shape`, `user_tracks_shape`, `user_tracks_invalid`, `answer_invalid` |

- 오류는 `InputError(code, message)`. `message`는 사용자에게 보여 줄 한국어 그대로다. 서버는 `422 {"error": code, "message": message}`로 바꾸면 된다
- `run_app.py`는 셋을 차례로 부르는 명령으로 남았다 (평가 도구·시험이 그대로 돌게). 결과 폴더 구조와 `app.json`은 바뀌지 않았고, `background.jpg`가 하나 늘었다
- 시험: `tests/test_pipeline.py` (모서리 먼저 → 탐지 → 판정이 저장된 결과와 같은지, 순서가 틀리면 알맞은 오류인지)

### 서버 (10-29, `src/server/`)

```bash
cd ~/MTM && .venv/bin/uvicorn src.server.app:app --port 8000   # API 서버 (주소 목록·시험: http://localhost:8000/docs)
cd ~/MTM && .venv/bin/python -m src.server.worker              # 작업자 (다른 터미널)
```

| 파일 | 하는 일 |
|---|---|
| `src/server/db.py` | SQLite `cases`, `jobs` 표. 사건 폴더 `data/cases/<id>/` (`MTM_CASES_DIR`로 바꿈). `take_job`: 가장 오래된 작업을 가져가되, 그 사건에 도는 작업이 있으면 건너뛰고, 판정 작업이 여러 개 쌓였으면 마지막 것만 남김 |
| `src/server/worker.py` | 작업 하나씩: `prepare` → 끝나면 모서리가 와 있으면 `solve`를 줄에 넣음, `solve`/`answer` → `pipeline.solve`. 입력 오류(`InputError`)는 사건 `error`에 남기고 직전 결과 상태로 되돌림. 그 밖의 예외는 `failed`. 켤 때 `running`으로 남은 작업을 다시 줄에 세움 |
| `src/server/app.py` | 3절 API. 모서리 검사(`set_scene`)만 바로 하고 나머지는 작업 줄로. 결과의 그림 경로는 `/api/cases/{id}/files/...` 주소로 바꿔서 줌. 원본 영상(`video.mp4`)과 사건 폴더 밖 파일은 안 내줌 |
| `tests/test_api.py` | 올리기 → 모서리(탐지 전) → 판정 → 답 두 번(마지막 것만) → 잘못된 답 → 지우기, 오류 코드들, 블랙박스. 기본은 저장된 탐지 결과를 넣어 몇 초, `MTM_SLOW=1`이면 탐지부터 (약 30초) |

`GET /api/cases/{id}` 응답 키: `id`, `name`, `status`, `stage`(준비 중이면 `detect`), `progress`(탐지 진행률 0~100), `saved`, `delete_at`, `post_id`, `error`(마지막 작업의 입력 오류 `{"error", "message"}` 또는 `null`), `background`·`scene_image`(그림 주소, 아직 없으면 `null`), `result`(`app.json`, 다시 판정하는 중에도 직전 결과), `created_at`.

환경 변수(`.env.example` 참고, `.env`는 git에 안 올라감): `MTM_JWT_SECRET`, `MTM_GOOGLE_CLIENT_IDS`, `MTM_DEV_LOGIN`, `MTM_CASES_DIR`(사건 폴더), `MTM_DB`(DB 파일), `MTM_MAX_UPLOAD_MB`(기본 200), `MTM_KEEP_DAYS`(기본 7), `MTM_HIDE_REPORTS`(기본 3), `MTM_CORS`, `MTM_JUDGE_DIR`.

추가 파일 (10-29): `src/server/auth.py`(소셜 토큰 확인 → JWT access 30분·refresh 30일, refresh는 `sessions` 표로 한 번만), `src/server/posts.py`(글 스냅샷·그림 복사·투표 전 AI 결과 숨김·집계). 작업자는 한 시간마다 보관 기간 지난 사건을 지운다(`clean_expired`, 도는 중인 사건은 다음 번에).

**서버 띄우기 (B가 앱을 붙일 때)**

```bash
cd ~/MTM && cp .env.example .env && bash tools/serve.sh
```

| 앱을 돌리는 곳 | 서버 주소 |
|---|---|
| 안드로이드 에뮬레이터 | `http://10.0.2.2:8000` |
| 같은 와이파이의 폰 | `http://<PC 내부 IP>:8000`. 서버는 WSL 안이라 Windows 쪽으로 포트를 열어야 함 (WSL 미러 네트워크 모드, 또는 `netsh interface portproxy`) |
| 다른 곳의 폰·시연 | Cloudflare Tunnel / ngrok의 HTTPS 주소 |

**같은 와이파이의 폰에서 붙기 (A PC 설정, 처음 한 번)**

WSL은 기본(NAT)으로 PC 안쪽 주소를 써서, 폰이 PC 와이파이 주소로 와도 WSL 서버까지 닿지 않는다. 미러 모드로 바꾸면 WSL이 PC와 같은 주소를 쓴다.

1. Windows `%USERPROFILE%\.wslconfig`에 다음을 쓰고 PowerShell에서 `wsl --shutdown` (WSL 다시 켜짐)
   ```ini
   [wsl2]
   networkingMode=mirrored
   ```
2. 관리자 PowerShell에서 8000번 포트를 열어 줌 (Windows 방화벽 + WSL용 Hyper-V 방화벽)
   ```powershell
   New-NetFirewallRule -DisplayName "MTM 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private
   New-NetFirewallHyperVRule -Name "MTM8000" -DisplayName "MTM 8000" -Direction Inbound -VMCreatorId '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' -Protocol TCP -LocalPorts 8000
   ```
3. `bash tools/serve.sh` → 폰 브라우저에서 `http://<PC 와이파이 IP>:8000/docs`가 열리면 됨 (PC IP는 PowerShell `ipconfig`의 Wi-Fi IPv4)

와이파이를 "공용 네트워크"로 잡아 두면 `-Profile Private` 규칙이 안 먹는다. 집·학교 와이파이를 개인 네트워크로 바꾸거나 규칙을 `-Profile Any`로. 학교 와이파이는 기기끼리 통신을 막아 둔 곳이 많아서, 그때는 아래 터널을 쓴다.

**다른 곳의 폰·시연 (터널)**

계정 없이 쓰는 Cloudflare 임시 터널. 켤 때마다 주소가 바뀐다 (고정 주소는 Cloudflare 계정 + 도메인 필요).

```bash
# 처음 한 번 (WSL): cloudflared 설치
curl -L -o /tmp/cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb && sudo dpkg -i /tmp/cloudflared.deb
# 서버를 켠 채로 다른 터미널에서
cloudflared tunnel --url http://localhost:8000
```

출력의 `https://<임의 이름>.trycloudflare.com`이 서버 주소다. HTTPS라 앱의 `network_security_config` 예외 없이 붙는다. 터널을 켜 두는 동안은 그 주소를 아는 누구나 서버에 접근할 수 있으므로(로그인은 필요) 시연이 끝나면 끈다.

안드로이드 9부터 `http://`는 기본으로 막혀서, 개발 중에는 앱의 `network_security_config`에 개발 주소만 허용한다. API 목록과 시험: `http://<서버>/docs` (오른쪽 위 Authorize에 access 토큰).

아직 안 한 것: 흐림 처리(번호판·얼굴)와 영상 공개, 학습용 사본 (`app_flow.md` 10절 4·5단계), 관리자 화면(숨긴 글 확인), 푸시 알림.

## 6. 판정 모듈(B) 연결

지금은 `../MTM_B/judge`(옆 폴더의 `feature/B`)를 직접 불러 쓴다. 서버에서는 **정해진 버전**을 써야 B가 고치는 중인 코드가 바로 서비스에 들어가지 않는다.

- 서버를 올릴 때 판정 모듈의 버전(태그, 예: `v0.13.1`)을 정해서 그 버전을 받아 둔다
- `app.json`의 `judge_version`에 그 버전이 이미 들어간다
- B가 장별 도표 파일(`rules_vehicle.json` 등)을 넣으면 A는 버전만 올리면 된다

## 7. 개인정보·보안

사고 영상에는 차량 번호, 얼굴이 찍혀 있고, 사고 당사자에게 민감한 자료다.

- 사건 id는 UUID. 목록 API는 두지 않는다 (id를 아는 사람만 볼 수 있음)
- **영상 보관 기간**: 보관함에 저장 안 한 사건은 7일 뒤 자동 삭제, 저장하면 사고 구간 압축 영상만 보관 (`app_flow.md` 7절). 사용자가 바로 지울 수 있게 `DELETE`를 둔다
- 서버 기록(log)에 영상 이름·답 내용을 남기지 않는다
- 올릴 수 있는 크기·길이 제한 (예: 200MB, 60초). 탐지 시간이 영상 길이에 비례해서 긴 영상은 서버를 오래 붙잡는다
- 로그인은 카카오·구글 소셜 로그인 + JWT (`app_flow.md` 2절). 분석 API를 먼저 로그인 없이 만들고, 2단계에서 사건에 주인을 붙인다. 투표 공개 영상·학습용 사본은 얼굴·번호판 흐림 처리 (`app_flow.md` 6·8절)

## 8. 정해야 할 것

| 항목 | 선택지 | 누가 |
|---|---|---|
| 앱 형태 | 웹(모바일 브라우저·PWA) / 모바일 앱(React Native, Flutter) | A·B 같이. API는 어느 쪽이든 같음 |
| 서버를 어디서 돌릴지 | 학교·개인 PC + 터널(시연용) / 클라우드 CPU / 클라우드 GPU | A. 비용과 시연 일정에 따라 |
| 영상 길이 제한, 구간 자르기 | 60초 제한 / 앱에서 사고 구간(예: 20초)을 잘라 올리기 | A·B. 자르기는 앱 화면이 필요함 |
| 영상 보관 기간 | 저장 안 하면 7일(안), 저장하면 보관 (`app_flow.md` 7절) | A·B |
| 로그인 | 카카오·구글 소셜 로그인으로 정함, 서버 완료 (10-29) | - |

## 9. 작업 순서 (A)

1. ~~`run_app.py` → `src/app/pipeline.py` (prepare / set_scene / solve), 예외 정리~~ (10-27 완료. 아래 "pipeline.py" 참고)
2. ~~FastAPI 서버 + SQLite 사건·작업 표 + 작업자 1개. 위 API 그대로~~ (10-29 완료, 5절 "서버")
3. ~~API 시험 (`tests/test_api.py`)~~ (10-29 완료)
4. ~~배경 그림·진행률·보관 기간 삭제~~ (10-29)
5. B가 화면을 붙일 수 있게 API 주소와 예시 응답을 정리 (FastAPI가 만드는 `/docs` 페이지 + 이 문서)
6. 그다음은 `app_flow.md` 10절 순서: 로그인·보관함 → 투표 → 흐림 처리 → 학습 데이터
