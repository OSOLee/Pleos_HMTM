# HMTM

사고 순간의 블랙박스 영상과 차량 주행 데이터를 함께 분석하여 “과실비율 인정기준”에 따른 참고용 과실비율과 그 판단 근거를 차량 화면에서 바로 제공하는 사고 분석 앱입니다.

분석은 백엔드 서버가 맡습니다. 심사에서는 PC에서 서버를 띄우고(모델 가중치 없이 정해 둔 결과를 내는 시나리오 분석기를 사용합니다), 에뮬레이터의 앱이 PC의 서버(`http://10.0.2.2:8000`)에 접속하도록 합니다.

## 실행 방법

Windows PowerShell에서 저장소 폴더를 기준으로 순서대로 실행합니다. 시연용 SD 카드 이미지는 에뮬레이터를 켠 뒤에는 바꿀 수 없으므로, 시연 데이터를 먼저 만듭니다.

1. 서버를 켭니다. 이 창은 켜 둡니다.

```powershell
cd backend
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
.venv\Scripts\python -m uvicorn src.server.app:app --host 0.0.0.0 --port 8000 --env-file .env
```

브라우저에서 `http://localhost:8000/`이 열리면 정상입니다. 처음 설치는 10분 넘게 걸릴 수 있습니다.

2. 다른 창에서 시연 데이터(데모 영상 7개가 든 SD 이미지와 차량 기록)를 만듭니다.

```powershell
powershell -ExecutionPolicy Bypass -File android\tools\sd.ps1 -Demo -NoEmulator
```

3. SD 이미지를 붙여 에뮬레이터를 켭니다.

```powershell
& "$env:LOCALAPPDATA\Android\Sdk\emulator\emulator.exe" -avd Pleos_Connect_v2.1.0 -read-only -sdcard "$env:USERPROFILE\hmtm-sd\sdcard.img" -timezone Asia/Seoul
```

4. 부팅이 끝나면 APK를 설치하고 차량 기록을 넣은 뒤 앱을 엽니다.

```powershell
$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
& $adb uninstall com.example.hmtm
& $adb install -r apk\이견없음_HMTM_release.apk
& $adb shell pm grant --user 10 com.example.hmtm android.car.permission.CAR_SPEED
powershell -ExecutionPolicy Bypass -File android\tools\sd.ps1 -RecordsOnly
& $adb shell am start --user 10 -n com.example.hmtm/.MainActivity
```

처음 실행하는 `uninstall`은 "설치된 앱이 없다"는 오류가 나도 괜찮습니다. 에뮬레이터를 `-read-only`로 켜면 예전에 설치했던 debug 앱이 다시 나타나 서명이 달라 설치가 실패하므로, 먼저 지우도록 넣어 두었습니다.

5. 앱에서 분석합니다.
   - 동의 화면에서 **동의하고 시작**을 누릅니다.
   - **블랙박스 영상으로 사고 분석**, **USB에서 영상 선택**을 누르고, 왼쪽의 `BLACKBOX` → `Normal` → `Front`에서 영상을 골라 **분석 시작**을 누릅니다.
   - 결과 화면에서 과실비율, 판단 근거, 질문, "차량 기록을 입증할 수 있으면" 카드를 확인합니다.

### 예시 시나리오 7개

SD 카드에는 합성 영상 7개가 들어 있습니다. 공모전 시연 영상(실제 블랙박스 영상 3건을 실제 분석기로 분석한 화면 녹화)과는 별개이며, 모델 가중치 없이 앱 전체 흐름을 직접 써 볼 수 있도록 만든 것입니다. 시나리오 분석기는 영상 내용을 보지 않고 파일 이름의 시나리오에 정해 둔 결과를 내므로, 아래 결과는 실제 영상 분석값이 아닙니다.

파일 선택 화면에서는 영상 이름이 잘려서 보입니다. 영상이 이름순으로 나열되므로 아래 순서대로 고르시면 됩니다.

1. `left_turn_motion`: 좌회전, 지시등을 켠 기록. 차량 기록이 과실에 영향을 주지 않습니다.
2. `left_turn_motion_nosignal`: 1번과 같은 영상, 지시등을 켜지 않은 기록. 기록을 입증하면 내 차 과실이 10 늘어납니다(70 : 30).
3. `mostly_unknown`: 대부분 알 수 없는 상황. 상대 종류 등을 질문으로 되묻습니다.
4. `no_collision_pick`: 충돌 순간을 찾지 못하는 영상. 사고 순간을 직접 고르면 60 : 40이 나옵니다.
5. `ped_crosswalk_unsignalized`: 신호 없는 횡단보도의 보행자. 보13, 보행자 과실 0%.
6. `right_turn_left_straight`: 우회전 중 왼쪽에서 직진하는 차. 차13-1, 60 : 40과 질문이 나옵니다. 시나리오 이름이 없는 영상의 기본값입니다.
7. `straight_motion_slowed`: 교차로 앞 서행. 기록을 입증하면 내 차 과실이 10 줄어듭니다(50 : 50).

## 테스트 환경 및 필요한 설정

개발과 시험은 아래 환경에서 했습니다.

- Windows 11 Home, Intel Core i7-1165G7(내장 그래픽)
- Android Studio 2026.2.2, Android Emulator 35.6.11
- JDK 21(Gradle용), Python 3.12(서버)
- Pleos Vehicle SDK 2.3.2

꼭 맞춰야 하는 설정은 다음과 같습니다.

- AVD의 `hw.sdCard`는 `yes`여야 합니다. `no`이면 `-sdcard`가 무시되어 `BLACKBOX`가 파일 선택 화면에 나오지 않습니다. AVD 폴더의 `config.ini`를 고친 뒤 에뮬레이터를 완전히 껐다가 다시 켭니다.
- Python은 3.12가 필요합니다. `sd.ps1`이 `py -3.12`를 사용합니다.
- Android SDK는 `%LOCALAPPDATA%\Android\Sdk`에 있어야 합니다. 다른 곳에 있으면 그 경로에 폴더 링크(`mklink /J`)를 만들어 주세요.
- 앱과 차량 기록은 에뮬레이터를 끄면 사라집니다. 켤 때마다 4번을 다시 실행합니다.
- Windows 방화벽이 8000번 포트를 막으면 허용해 주세요.

## 개발에 사용한 Pleos Connect 에뮬레이터

| 항목 | 값 |
|---|---|
| AVD | `Pleos_Connect_v2.1.0` (Android 14, API 34, Automotive) |
| 시스템 이미지 | `system-images\android-34\pleos_car_emulator\x86_64` |
| 화면 해상도 / 밀도 | 2560 × 1440 / 160 dpi |
| 앱 창 | 1682 × 1210 px(앱 1개), 약 849 × 1210 px(1:1 분할) |

## APK

[`apk/이견없음_HMTM_release.apk`](apk/이견없음_HMTM_release.apk) (62,514,736 바이트, 버전 0.1.0)
