# HMTM 실행 방법

README의 "실행 방법"을 자세히 적은 문서다. Windows 기준(PowerShell)이며, 명령은 저장소 폴더에서 시작한다.

- [1. 준비물](#1-준비물)
- [2. backend (서버)](#2-backend-서버)
- [3. 앱 (Android Automotive / Pleos Connect)](#3-앱-android-automotive--pleos-connect)
- [4. 에뮬레이터 데모 한 번에 준비](#4-에뮬레이터-데모-한-번에-준비)
- [5. 수동으로 확인하는 방법](#5-수동으로-확인하는-방법)
- [6. 시험](#6-시험)

## 1. 준비물

| 항목 | 버전 | 비고 |
|---|---|---|
| Python | 3.12 | backend |
| Android Studio | 최신 | `android/` 폴더를 연다 |
| JDK (Gradle용) | 21 | 25는 Gradle 8.13과 맞지 않음 |
| AGP / Gradle | 8.13.2 / 8.13 | 고정 |
| Kotlin / Compose BOM | 2.0.21 / 2024.09.03 | compileSdk 34 |
| Pleos Vehicle SDK | 2.3.2 | Gradle이 Pleos 저장소에서 받음 |
| 에뮬레이터 | Pleos Connect Emulator (API 34) | AVD 이름 예: `Pleos_Connect_v2.1.0` |

## 2. backend (서버)

### 2.1 설치

```powershell
cd backend
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt       # 실행용 (torch CPU 판 포함)
.venv\Scripts\python -m pip install -r requirements-dev.txt   # 시험용 (pytest 등)
```

- OpenCV는 `opencv-python-headless`만 쓴다 (`opencv-python`과 같이 깔면 충돌한다).
- 설정 예시는 `backend/.env.example`. 복사해서 `.env`로 쓴다 (`.env`는 git에 올리지 않는다).

### 2.2 서버 띄우기 (시나리오 분석기, 기본)

시나리오 분석기(`HMTM_BB_ANALYZER=fake`, 기본값)는 정해 둔 시나리오로 분석 결과를 흉내 낸다. 모델 가중치 없이 앱 전체 흐름을 볼 수 있다.
API 프로세스 안에서 분석하므로 서버만 띄우면 된다.

```powershell
cd backend
$env:MTM_DEV_LOGIN="1"                       # 개발용 로그인 켜기
$env:MTM_JWT_SECRET="change-me-to-a-random-32-char-string"   # 예시 값. 32자 이상 아무 값
.venv\Scripts\python -m uvicorn src.server.app:app --host 0.0.0.0 --port 8000
```

- 확인: `curl http://localhost:8000/` → `{"service": ...}`. API 문서는 `http://localhost:8000/docs`.
- `MTM_JWT_SECRET`을 비우면 서버를 켤 때마다 키가 바뀌어 앱이 다시 로그인한다.
- `.env`를 쓰려면 `--env-file .env`를 붙인다.
- 에뮬레이터에서는 `http://10.0.2.2:8000`이 이 PC의 서버다.

### 2.3 진짜 분석기 (`mtm`)

YOLO 기반 영상 분석기다. **가중치가 저장소에 없으므로** `backend/models/`에 따로 받아 두어야 한다 (README "데이터·모델 안내").
파일 이름·sha256·크기는 `backend/models.json`과 같아야 하며, 다르거나 없으면 `503 analyzer_not_ready`를 돌려준다.

서버와 분석 작업자를 각각 다른 창에서, 같은 환경변수로 띄운다.

```powershell
# 창 1: API 서버
cd backend
$env:HMTM_BB_ANALYZER="mtm"; $env:MTM_DEV_LOGIN="1"; $env:MTM_JWT_SECRET="change-me-to-a-random-32-char-string"
.venv\Scripts\python -m uvicorn src.server.app:app --host 0.0.0.0 --port 8000

# 창 2: 분석 작업자 (한 번에 영상 하나, 작업자는 하나만)
cd backend
$env:HMTM_BB_ANALYZER="mtm"
.venv\Scripts\python -m src.blackbox.worker          # 남은 것만 처리하고 끝내려면 --once
```

| 환경변수 | 뜻 |
|---|---|
| `HMTM_BB_IMGSZ=640` | CPU에서 느릴 때 추적 해상도를 낮춤 (상대 종류 신호는 960 그대로) |
| `HMTM_KEEP_VIDEO=1` | 분석 뒤 원본 영상을 지우지 않음 (개발용) |
| `HMTM_BB_MODEL_CHECK=0` | 가중치 검사 끄기 (실험용) |
| `MTM_DB`, `MTM_CASES_DIR`, `HMTM_BB_CASES_DIR` | DB·사건 폴더 위치. 바꾸면 두 창에 같은 값을 준다 |

### 2.4 로그인 (API를 직접 부를 때)

1. `POST /api/auth/dev {"token": "<아무 이름>"}` → `{access, refresh, ...}`. 같은 이름이면 같은 회원.
2. 처음 회원은 `PUT /api/me {"nickname": "<2~12자>", "agree_terms": true}`로 가입을 끝낸다 (안 하면 `403 signup_required`).
3. 요청 머리에 `Authorization: Bearer <access>`. access는 30분, 만료되면 `POST /api/token/refresh {"refresh"}`.

블랙박스 사건 API: `POST /api/bb-cases`(multipart `video`·`meta`), `GET /api/bb-cases/{id}`, `PUT /api/bb-cases/{id}/answers`, `PUT /api/bb-cases/{id}/collision`.

## 3. 앱 (Android Automotive / Pleos Connect)

### 3.1 빌드

```powershell
cd android
$env:JAVA_HOME="<JDK 21 경로>"     # 예: $HOME\.jdks\jbr-21.0.11
.\gradlew assembleDebug            # → app\build\outputs\apk\debug\app-debug.apk
.\gradlew testDebugUnitTest        # JVM 단위 시험 (기기 없음)
.\gradlew assembleRelease          # → app\build\outputs\apk\release\app-release.apk (서명 값이 없으면 app-release-unsigned.apk)
```

- release 서명 값은 **저장소 밖**에서만 읽는다. 사용자 `~/.gradle/gradle.properties`(Windows는 `%USERPROFILE%\.gradle\gradle.properties`) 또는 같은 이름의 환경변수:
  ```properties
  HMTM_RELEASE_STORE_FILE=<키 파일 경로, 예: C:/keys/hmtm-release.jks>
  HMTM_RELEASE_STORE_PASSWORD=<비밀번호>
  HMTM_RELEASE_KEY_ALIAS=<별칭>
  HMTM_RELEASE_KEY_PASSWORD=<비밀번호>
  ```
  하나라도 없으면 서명 없이 빌드된다. 키 파일(`*.jks`, `*.keystore`)은 `.gitignore`에 들어 있다.
- release도 코드 축소(minify)를 끄고, 시연용 차량 기록을 `adb run-as`로 넣을 수 있게 `debuggable`이다.

- Android SDK 위치는 `android/local.properties`의 `sdk.dir` 또는 환경변수 `ANDROID_HOME` (Android Studio로 열면 자동으로 만들어진다).
- 서버 주소는 `android/local.properties`의 `backend.url`. 없으면 `http://10.0.2.2:8000`(에뮬레이터에서 본 내 PC).
  평문 HTTP는 `10.0.2.2`만 허용한다 (`res/xml/network_security_config.xml`). 실기기는 PC IP + 방화벽 허용이 필요하다.
- Pleos 차량은 운전자 프로필이 사용자 10번이다. 앱 데이터 확인: `adb shell run-as com.example.hmtm --user 10 ls files/loop`

### 3.2 설치·권한

```powershell
$adb="$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
& $adb install -r android\app\build\outputs\apk\debug\app-debug.apk
& $adb shell pm grant --user 10 com.example.hmtm android.car.permission.CAR_SPEED
& $adb shell am start --user 10 -n com.example.hmtm/.MainActivity
```

처음 열면 "사고 기록을 시작할까요?" 안내가 나온다. "동의하고 시작" → 홈에 "기록 중".

## 4. 에뮬레이터 데모 한 번에 준비

에뮬레이터에는 USB 메모리를 꽂을 수 없어서 **가상 SD 카드(FAT32 이미지, 볼륨 이름 `BLACKBOX`)**로 블랙박스 메모리를 흉내 낸다.
`android/tools/sd.ps1`이 시험 영상 → SD 이미지 → 시나리오에 맞는 차량 기록 → 에뮬레이터 실행 → 앱 설치·권한 → 기록 넣기를 한 번에 한다.

준비:
1. backend 가상환경(`backend\.venv`)과 앱 빌드(`.\gradlew assembleDebug`).
2. SD 이미지를 만드는 `pyfatfs`는 따로 만든 가상환경에 설치한다 (스크립트가 안내).
   ```powershell
   py -3.12 -m venv $env:TEMP\fatvenv
   & $env:TEMP\fatvenv\Scripts\python -m pip install pyfatfs "setuptools<81"
   ```
3. 켜진 에뮬레이터를 끈다 (이미지는 켜진 동안 바꿀 수 없다).

실행:
```powershell
powershell -ExecutionPolicy Bypass -File android\tools\sd.ps1 -Demo
```

그 뒤 backend 서버를 띄우고(2.2) 앱 → "블랙박스 영상으로 사고 분석" → "USB에서 영상 선택" → `BLACKBOX` → `Normal/Front` → 영상 → "분석 시작".

| 데모 영상 (시나리오) | 보이는 것 |
|---|---|
| `right_turn_left_straight` | 차대차, 차13-1 "내 차 60 : 상대 40", 질문 5개 |
| `ped_crosswalk_unsignalized` | 차대보행자, 보13 "보행자 과실 0%", 가감 요소 질문 |
| `mostly_unknown` | 상대 종류를 추정만 함 → "상대는 무엇이었나요?" 질문 |
| `left_turn_motion` | 좌회전 지시등 켬 → "차량 기록은 이 사고의 과실에 영향을 주지 않아요" |
| `left_turn_motion_nosignal` | 지시등 안 켬 → 기록 입증 시 "내 차 70 : 상대 30" (+10) |
| `straight_motion_slowed` | 교차로 앞 서행 → 기록 입증 시 "내 차 50 : 상대 50" (−10) |
| `no_collision_pick` | "사고 순간 확인 필요" → 사고 순간 고르기 → 18.2초 → "내 차 60 : 상대 40" |

| `sd.ps1` 옵션 | 뜻 |
|---|---|
| (없음) | 영상 폴더(`%USERPROFILE%\hmtm-sd\videos`) 그대로 |
| `-Demo` | 위 일곱 데모 영상 |
| `-Now` | 영상 이름을 지금 기준 시각(몇 분 전)으로 바꿈. 직접 넣은 블랙박스 영상에 |
| `-Scenario <이름>` | 모든 영상에 시나리오 분석기 시나리오를 붙임. 목록은 `-ListScenarios` |
| `-NoRecord` | 차량 기록 없이 영상만 |
| `-RecordsOnly` | 켜진 에뮬레이터에 차량 기록만 다시 넣기 |
| `-NoEmulator` | 이미지·기록 파일만 만들기 |

- 화면 캡처: 이 AVD에서는 `adb exec-out screencap`이 흰 화면이라 `adb emu screenrecord screenshot <파일.png>`를 쓴다.
- 영상 이름의 촬영 시각이 72시간보다 오래됐거나 미래면 경고가 나온다 → `-Now`.

## 5. 수동으로 확인하는 방법

### 5.1 SD 카드를 직접 만들기

```powershell
backend\.venv\Scripts\python android\tools\make_test_video.py $env:TEMP\20261109_143012_F.mp4 --seconds 30
& $env:TEMP\fatvenv\Scripts\python android\tools\make_sdcard.py $env:TEMP\blackbox.img $env:TEMP\20261109_143012_F.mp4
& $env:LOCALAPPDATA\Android\Sdk\emulator\emulator.exe -avd Pleos_Connect_v2.1.0 -read-only -sdcard $env:TEMP\blackbox.img
& $adb shell service call alarm 3 s16 Asia/Seoul     # 기본 시간대가 America/Los_Angeles라 서울로
```

카드 안 경로는 `Normal/Front/<파일>`. 파일 이름의 시각이 촬영 시작 시각 후보가 된다.

### 5.2 주행 기록 만들기

차량 기록을 영상에 붙이려면 **영상 파일 이름의 시각 구간에 앱이 기록하고 있어야** 한다.
파일 이름을 지금부터 5~10분 뒤 시각으로 만들고, 그 시각 + 30초가 지날 때까지 앱을 켜 둔다.

- 에뮬레이터 옆 막대 `…`(Extended controls) → 차량 데이터(Car data)에서 속도·기어를 바꾼다.
- 급제동(시속 20km 이상에서 1초에 15km/h 넘게 감속)을 하면 15초 뒤 홈 "사고 의심 순간"에 생긴다.
- 값을 안 바꿔도 100ms마다 기록이 쌓인다 (속도 0, 기어 P).

### 5.3 확인할 화면

| 화면 | 확인할 것 |
|---|---|
| 영상 선택 | 길이·촬영 시작 시각, "차량 기록" 행에 구간·기록 개수와 "시각 대략 일치" 배지 |
| 분석 중 | 네 단계 진행 |
| 결과 | 과실비율, 적용 기준(도표 번호), 근거와 출처 배지(영상·차량 기록·내 답변·추정), "임시 결과 · 질문 N개 남음" |
| 질문 | 영상 추정값은 "영상 추정" 배지만 붙고 미리 골라져 있지 않음. "잘 모르겠어요"는 답 없이 다음으로 |
| 주행 중 | 속도 3km/h 이상(또는 기어 D·R)이면 질문 보기·다음이 꺼지고 "정차 후 사용할 수 있어요" |
| 차량 기록 카드 | "차량 기록을 입증할 수 있으면" → 바뀌는 비율과 이유, "기록 보기"에서 속도·지시등·브레이크 그래프 |
| 지난 분석 | 최근 것부터, "차량 기록 있음"/"영상만", 삭제 |
| 기록 설정 | 자동 기록 끄기, "모든 기록 삭제"(선택: 서버의 분석 사건도) |
| 영상 다시 보기 | 앱 안에서 사고 3초 전부터 재생. USB가 없으면 "영상을 열 수 없어요" |

## 6. 시험

```powershell
cd backend
.venv\Scripts\python -m pytest                   # backend 전체
.venv\Scripts\python -m pytest tests\golden      # 결과 고정 시험 (데모 사건 응답 전체 비교)
cd ..\android
.\gradlew testDebugUnitTest                      # 앱 JVM 단위 시험
```

- 결과 고정 시험은 시나리오 분석기로 데모 사건을 만들고 정해진 답·사고 순간 고르기 뒤 응답 전체를 `tests/golden/data/`와 비교한다 (`backend/tests/golden/README.md`).
- 일부 시험은 저장소에 없는 영상·가중치가 필요해 건너뛴다.
