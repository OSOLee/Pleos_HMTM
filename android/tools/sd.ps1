<#
.SYNOPSIS
  에뮬레이터 시험·데모 데이터를 한 번에 준비한다: 블랙박스 SD 이미지 + 시나리오별 차량 기록 + Pleos 에뮬레이터 실행.

.DESCRIPTION
  1. 영상 폴더(기본 %USERPROFILE%\hmtm-sd\videos)를 정리한다. 비었으면 시험 영상을 만든다.
  2. 영상을 넣은 FAT32 SD 이미지(기본 %USERPROFILE%\hmtm-sd\sdcard.img, 볼륨 BLACKBOX, 폴더 Normal\Front)를 만든다.
  3. 영상 파일 이름의 시각·시나리오(__scn-)에 맞춰 차량 기록(루프 CSV, 100ms)을 만든다.
  4. 그 이미지를 붙여 에뮬레이터를 켜고(-read-only, 시간대 Asia/Seoul), 앱을 설치하고, 차량 기록을 앱(사용자 10)에 넣는다.
  backend 서버는 따로 띄운다 (docs/SETUP.md 2.2 "서버 띄우기").

.EXAMPLE
  android\tools\sd.ps1 -Demo                 # 데모 일곱 시나리오 (차대차 질문 / 보행자 / 상대 종류 추정 / 좌회전 지시등 켬·안 켬 / 직진 서행 / 사고 순간 고르기)
  android\tools\sd.ps1                       # 영상 폴더 그대로 (비었으면 시험 영상 하나)
  android\tools\sd.ps1 -Now -Scenario rear_end_lead   # 내 영상 이름을 지금 기준 시각으로 + 시나리오 표시
  android\tools\sd.ps1 -NoRecord             # 차량 기록 없이 영상만
  android\tools\sd.ps1 -RecordsOnly          # 켜진 에뮬레이터에 차량 기록만 다시 넣기
#>
param(
    [string]$VideoDir = "$env:USERPROFILE\hmtm-sd\videos",
    [string]$Image = "$env:USERPROFILE\hmtm-sd\sdcard.img",
    [switch]$Demo,          # 데모 일곱 시나리오 영상(전 데모 영상은 지움)
    [switch]$Now,           # 모든 영상 이름을 지금 기준 시각(몇 분 전)으로
    [string]$Scenario,      # 모든 영상에 __scn-<이름> (가짜 분석기 시나리오)
    [switch]$NoRecord,      # 차량 기록 없이 영상만
    [switch]$RecordsOnly,   # 켜진 에뮬레이터에 차량 기록만 다시 넣기 (이미지·영상 이름은 그대로)
    [switch]$NoEmulator,    # 이미지·기록 파일만 만들고 에뮬레이터는 켜지 않음
    [switch]$ListScenarios,
    [double]$Seconds = 30,  # 만드는 시험 영상 길이
    [string]$Avd = "Pleos_Connect_v2.1.0"
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"   # 하위 명령 출력과 순서가 섞이지 않게

$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
$Py = "$Root\backend\.venv\Scripts\python.exe"
$Tool = "$PSScriptRoot\sd_data.py"
$Work = Split-Path -Parent $Image
$Records = Join-Path $Work "records"
$FatVenv = Join-Path $Work "fatvenv"
$Sdk = "$env:LOCALAPPDATA\Android\Sdk"
$Adb = "$Sdk\platform-tools\adb.exe"
$Emu = "$Sdk\emulator\emulator.exe"
$Apk = "$Root\android\app\build\outputs\apk\debug\app-debug.apk"
$Pkg = "com.example.hmtm"

function Step($msg) { Write-Host ""; Write-Host "== $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host "[오류] $msg" -ForegroundColor Red; exit 1 }
function Warn($msg) { Write-Host "[안내] $msg" -ForegroundColor Yellow }
function Invoke-SdData { & $Py $Tool @args; if ($LASTEXITCODE -ne 0) { Fail "sd_data.py $($args[0]) 실패" } }
function AdbOut { (& $Adb @args 2>&1 | Out-String).Trim() }

if (-not (Test-Path $Py)) { Fail "backend 가상환경이 없어요: $Py (docs/SETUP.md 2.1 '설치')" }
if ($ListScenarios) { & $Py $Tool scenarios; exit $LASTEXITCODE }
New-Item -ItemType Directory -Force $VideoDir, $Work | Out-Null

$running = @((& $Adb devices 2>$null) | Select-String '^(emulator-\d+)\s+device' | ForEach-Object { $_.Matches[0].Groups[1].Value })

function Set-SeoulTz {
    # 자동 시간대(위치 기반)가 켜져 있으면 몇 초 뒤 America/Los_Angeles로 되돌린다 → 끄고 서울로.
    # 시간대가 틀리면 앱이 파일 이름 시각을 LA 시각으로 읽어 "촬영 시각을 확인해 주세요" + 차량 기록 없음이 된다
    AdbOut shell settings put global auto_time_zone 0 | Out-Null
    AdbOut shell service call alarm 3 s16 Asia/Seoul | Out-Null
    Start-Sleep -Seconds 5
    $tz = AdbOut shell getprop persist.sys.timezone
    if ($tz -ne "Asia/Seoul") { Warn "시간대가 $tz 이에요. 설정 → 날짜·시간에서 서울로 바꿔 주세요" }
    return $tz
}

function Push-Records {
    if ($NoRecord) { Warn "-NoRecord: 차량 기록을 넣지 않아요 (영상만)"; return }
    Step "차량 기록을 앱(사용자 10)에 넣기"
    $pkgs = AdbOut shell pm list packages --user 10 $Pkg
    if ($pkgs -notmatch "package:$Pkg") {
        Warn "앱이 설치돼 있지 않아 차량 기록을 못 넣었어요. 앱을 빌드·설치한 뒤 'sd.ps1 -RecordsOnly'"
        return
    }
    Invoke-SdData push --adb $Adb --dir $Records --user 10
}

# ---- 켜진 에뮬레이터에 차량 기록만 ----
if ($RecordsOnly) {
    if ($running.Count -eq 0) { Fail "켜진 에뮬레이터가 없어요. -RecordsOnly 없이 실행하면 이미지를 붙여 켭니다" }
    $tz = Set-SeoulTz
    Step "차량 기록 만들기 ($VideoDir)"
    Invoke-SdData records --videos $VideoDir --out $Records
    Push-Records
    exit 0
}

if ($running.Count -gt 0 -and -not $NoEmulator) {
    Warn "에뮬레이터가 켜져 있어요 ($($running -join ', ')). SD 이미지는 에뮬레이터가 켜진 동안 바꿀 수 없어요."
    Write-Host "  - 에뮬레이터를 끄고(창 닫기 또는 '$Adb emu kill') 이 명령을 다시 실행하세요."
    Write-Host "  - 영상은 그대로 두고 차량 기록만 다시 넣으려면: android\tools\sd.ps1 -RecordsOnly"
    exit 1
}

# ---- 1. 영상 ----
Step "영상 준비 ($VideoDir)"
$prep = @("prepare", "--videos", $VideoDir, "--seconds", $Seconds)
if ($Demo) { $prep += "--demo" }
if ($Now) { $prep += "--now" }
if ($Scenario -and -not $Demo) { $prep += @("--scenario", $Scenario) }
Invoke-SdData @prep
$videos = @(Get-ChildItem $VideoDir -File | Where-Object { $_.Extension -match '^\.(mp4|avi|mov|mkv|ts)$' })
if ($videos.Count -eq 0) { Fail "영상이 없어요: $VideoDir" }

# ---- 2. SD 이미지 ----
Step "SD 이미지 만들기 ($Image)"
$fatPy = "$FatVenv\Scripts\python.exe"
if (-not (Test-Path $fatPy)) {
    Write-Host "pyfatfs 가상환경을 처음 한 번 만들어요: $FatVenv"
    & py -3.12 -m venv $FatVenv
    & $fatPy -m pip install --quiet pyfatfs "setuptools<81"
    if ($LASTEXITCODE -ne 0) { Remove-Item -Recurse -Force $FatVenv; Fail "pyfatfs 설치 실패" }
}
$sizeMb = [int][Math]::Max(128, [Math]::Ceiling((($videos | Measure-Object Length -Sum).Sum / 1MB) * 1.2) + 64)
& $fatPy "$PSScriptRoot\make_sdcard.py" $Image @($videos.FullName) --size-mb $sizeMb
if ($LASTEXITCODE -ne 0) { Fail "SD 이미지를 못 만들었어요 (에뮬레이터가 이미지를 쓰고 있으면 끄고 다시)" }

# ---- 3. 차량 기록 파일 ----
if (-not $NoRecord) {
    Step "차량 기록 만들기 ($Records)"
    Invoke-SdData records --videos $VideoDir --out $Records
}

if ($NoEmulator) {
    Write-Host ""
    Write-Host "에뮬레이터는 켜지 않았어요. 켜기: & `"$Emu`" -avd $Avd -read-only -sdcard `"$Image`" -timezone Asia/Seoul"
    Write-Host "켠 뒤 차량 기록 넣기: android\tools\sd.ps1 -RecordsOnly"
    exit 0
}

# ---- 4. 에뮬레이터 ----
Step "에뮬레이터 켜기 ($Avd, SD 이미지, 시간대 Asia/Seoul)"
Start-Process -FilePath $Emu -ArgumentList @("-avd", $Avd, "-read-only", "-sdcard", "`"$Image`"", "-timezone", "Asia/Seoul") | Out-Null
& $Adb wait-for-device
$deadline = (Get-Date).AddMinutes(6)
while ((AdbOut shell getprop sys.boot_completed) -ne "1") {
    if ((Get-Date) -gt $deadline) { Fail "에뮬레이터 부팅이 6분 안에 끝나지 않았어요" }
    Start-Sleep -Seconds 3
}
$tz = Set-SeoulTz
Write-Host "부팅 완료, 시간대 $tz, 기기 시각 $(AdbOut shell date)"

if (Test-Path $Apk) {
    Write-Host "앱 설치: $Apk"
    AdbOut install -r $Apk | Write-Host
    AdbOut shell pm grant --user 10 $Pkg android.car.permission.CAR_SPEED | Out-Null
} else {
    Warn "앱 APK가 없어요. 빌드: cd android; `$env:JAVA_HOME=`"`$HOME\.jdks\jbr-21.0.11`"; .\gradlew assembleDebug"
}

# 운전자 사용자 10이 켜질 때까지 (run-as가 될 때까지)
$deadline = (Get-Date).AddMinutes(3)
while ((AdbOut shell run-as $Pkg --user 10 pwd) -notmatch "^/data") {
    if ((Get-Date) -gt $deadline) { Warn "사용자 10의 앱 폴더에 아직 못 들어가요"; break }
    Start-Sleep -Seconds 3
}
Push-Records

Step "준비 끝"
Write-Host "SD 이미지: $Image  (파일 선택 화면 왼쪽 BLACKBOX → Normal → Front)"
Write-Host "영상: $VideoDir"
Write-Host "다음: backend 서버를 띄우고(docs/SETUP.md 2.2 '서버 띄우기') 앱을 연다:"
Write-Host "  & `"$Adb`" shell am start --user 10 -n $Pkg/.MainActivity"
Write-Host "  홈 '블랙박스 영상으로 사고 분석' → 'USB에서 영상 선택' → BLACKBOX → Normal/Front → 영상 → '분석 시작'"
