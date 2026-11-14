# backend 코드 출처

HMTM은 MTM과 독립된 프로젝트이며 이 시점 이후 변경은 서로 반영되지 않는다.

## 출처

| 항목 | 값 |
|---|---|
| 저장소 | https://github.com/OSOLee/MTM.git |
| 커밋 | `32faa32` (`32faa32d4441d7ed1c7c3ba76807b648443e4b30`, "Merge feature/B into main", 2026-11-08 16:10 +0900) |
| 가져온 날짜 | 2026-11-08 |
| 방법 | `git archive 32faa32`로 추출. MTM 내부 폴더 구조 그대로 `backend/`에 넣음 |
| 가져온 시점 `judge/VERSION` | `0.13.1` |
| 가져온 시점 `detector/VERSION` | `0.17.0` |

분류 근거는 가져오기 전에 MTM 브랜치를 조사한 내부 문서다 (제출본에는 넣지 않음).

## 가져온 범위 (backend/ 161개 파일)

- 조사 문서의 "가져올 것" 표 전체
  - `judge/` (판정 엔진, `rules.json`·`modifiers.json`, `judge/tests/`, `judge/docs/`)
  - `src/analyze/`, `src/app/`, `src/make_scene.py`, `src/__init__.py`, `run_app.py`
  - `detector/` (YOLO 학습·변환), `src/dataset/` (신호등 CNN 학습)
  - `src/server/` (FastAPI), `tools/serve.sh`, `.env.example`
  - `requirements.txt`, `tests/`
- 추가로 가져온 것
  - 블랙박스 실험 코드: `src/analyze/ego_motion.py`, `lead_vehicle.py`, `bb_signal.py`, `tools/blackbox_tracks.py`, `tools/val_bb_signal.py`
  - `detector/colab_train.ipynb`
  - `src/eval/` 전체, `tools/evaluate/` 전체, `tools/data/` 전체
  - `tools/draw_scene.py`, `tools/pick_corners.py`
  - `scenes/`, `splits/`
- MTM `docs/` (`docs/archive/` 제외) 8개 → `backend/`가 아니라 HMTM `docs/engine/`

## 제외한 범위

- `app/` (Flutter 앱, `MTM_App_Preview.pdf` 포함), `.vscode/`, `.claude/`
- 루트 `README.md`, `CHANGELOG.md`
- `src/analyze/light_color.py` (어디서도 import하지 않음)
- `tools/experiments/` (1회성 실험 7개)
- `docs/archive/`
- `feature/A` 전용 구버전 21개: `32faa32`(main)에는 이미 없어서 따로 걸러낼 것이 없었음
- 루트 `.gitattributes`: 가져오기 기준에 없음
- 루트 `.gitignore`: 파일로 가져오지 않고 Python 관련 항목만 HMTM 루트 `.gitignore`에 병합 (폴더 패턴은 `backend/` 기준으로 고정)
- `.claude/` 규칙: 필요한 내용만 HMTM 개발 규칙 문서로 옮김 (실행 방법은 `docs/SETUP.md`)

## 가져온 뒤 수정한 것

- `backend/src/app/pipeline.py`: `JUDGE_DIR`를 `../MTM_B/judge`에서 `backend/judge`(파일 위치 기준 절대경로)로 변경
- `backend/tests/test_rules_coverage.py`: `JUDGE` 경로를 `../MTM_B/judge`에서 `backend/judge`로 변경 (docstring 포함)
- `backend/tools/evaluate/modifier_audit.py`: `MTM_JUDGE_DIR` 기본값을 `../MTM_B/judge`에서 `backend/judge`(파일 위치 기준)로 변경
- `backend/src/app/judge_bridge.py`, `backend/tests/test_api.py`, `backend/tests/test_pipeline.py`: `../MTM_B/judge`를 언급하던 주석을 현재 경로에 맞게 수정
- `backend/requirements.txt`: `py7zr` 추가 (`detector/convert_cvat.py`가 사용)
- `backend/requirements-dev.txt` 새로 만듦: `-r requirements.txt` + `pytest==9.2.0` (실행용과 개발용 분리)
- `judge/` 안의 파일은 가져올 때 수정하지 않음. 이후 HMTM에서 `hmtm-주.부.수`로 관리하며 변경은 `backend/judge/CHANGELOG.md`에 남긴다
- `backend/src/server/app.py` 끝에 두 줄 (`358ada1`, `387e33e`): `src.vehicle.api`·`src.blackbox.api`의 `install(app)` 호출. 이유: 차량 사건(`/api/vehicle-cases`)·블랙박스 사건(`/api/bb-cases`) 라우트를 MTM 서버 앱에 붙이기 위해. 코드는 `src/vehicle/`, `src/blackbox/`에 따로 둠
- `backend/src/app/judge_bridge.py` 한 줄 (`1b5a201`, judge hmtm-0.1.0): `engine.judge(facts, engine.load_rules(), engine.load_catalog())` → `engine.judge(facts)`. 이유: hmtm-0.1.0부터 엔진이 충돌 당사자 차종으로 사고 유형(차대차·보행자·자전거)을 정하고 그 유형의 규칙 파일을 스스로 읽기 때문

## MTM 블랙박스 분석 코드 (HMTM_BB_ANALYZER=mtm)

2026-11-10 MTM(`OSOLee/MTM`) `feature/server` **커밋 `bcc4e21`** 의 블랙박스 분석 코드를 `backend/src/blackbox/video_lib/`에 **복사**했다.
복사한 파일 7개는 `bcc4e21`의 같은 파일과 (첫 줄 출처 주석과 import 경로만 빼면) 글자까지 같다. **단 `bb_kind.py`는 11-11에 `imgsz`·`conf` 인자를 받게 고친 MTM `2f890d4`로 다시 복사했다** (나머지 6개는 그대로 `bcc4e21`). **11-12에는 `bb_partner.py`·`bb_scene.py`·`bb_crosswalk.py`·`scene_crosswalk.py` 4개를 MTM `f1cd685`로 다시 복사했다**(`bb_partner.run(collision_t=)` 사고 순간 고르기, 횡단보도 모델 conf 0.15, 교차로 장면을 충돌 직전 5장면으로. 모두 B 요청이다). 그래서 지금 복사 기준은 `bcc4e21`(5개) · `2f890d4`(`bb_kind.py`) · `f1cd685`(4개)로 섞여 있다. `f1cd685`는 로컬 커밋이고 MTM에 push 전이면 `feature/server`에는 아직 없다. 이 시점은 이전에 적었던 `34c4557`보다 커밋 3개 뒤다: `24dc973` 평가 도구(scene_eval, 복사 대상 아님), `23be018` 장면·횡단보도 연결(`bb_scene`, `bb_crosswalk`, `scene_crosswalk`), `bcc4e21` `bb_output` 주석 정리. 세 커밋 모두 MTM `feature/server`와 `feature/app-integration`에 push돼 있다.
`src/analyze`는 MTM 영역이라 고치지 않고, 복사본의 `from src.analyze import ...`만 `from src.blackbox.video_lib import ...`로 바꿨다 (각 파일 첫 줄에 출처 표시).
MTM 쪽을 고치면 같은 방법으로 다시 복사한다.
`ego_motion`과 `track_video`는 복사하지 않고 HMTM에 있던 `32faa32` 판(`backend/src/analyze/`)을 쓴다.

| 파일 | 하는 일 |
|---|---|
| `bb_partner.py` | 사고 순간(충격 후보·멈춤 경계)과 상대 차 고르기 |
| `bb_facts.py` | 사실(facts) 만들기. 상대 종류는 사용자 답 > 사고 직전 탐지 신호 > 자동차류 |
| `bb_kind.py` | 사고 직전 2초에 보행자·자전거 신호 (`bb_v2` 모델, 286개 영상 시험: 민감도 70%, 오경보 5%) |
| `bb_scene.py`, `bb_crosswalk.py` | 장면 분류(M6)·횡단보도(M5) 모델 실행부 (모델 파일이 없으면 건너뜀) |
| `scene_crosswalk.py` | B가 전달한 참고 구현(초안) 그대로 |
| `bb_output.py` | 위 결과를 bb-0.2 출력(`ego`/`other`, 값 객체)으로 변환 |

- `backend/src/blackbox/video_analyzer.py` 새 파일 (`bb_partner`가 사고 순간을 못 찾으면 `status: "no_collision"`, `collision.t: null`로 내고 영상 끝 시각은 `hints.collision_candidates`에 후보로 둔다. 상대의 `entry_from`·`movement`·`lead_order`는 `guess`. 복사본 `bb_facts.py`는 MTM과 갈라지지 않게 고치지 않고 여기서 거른다. 이 PC 기록은 295개 중 26개(8.8%)가 해당): `analyze()`가 탐지·추적 → 촬영 차 움직임 → 사고 순간·상대 → 사고 직전 신호 → 장면·횡단보도 → bb-0.2 순서로 돈다. 탐지 모델(`HMTM_BB_DETECTOR`, 기본 `models/bb_v1.pt`)이 없으면 `AnalyzerNotReady`.
- `backend/src/blackbox/analyzer.py`의 `MtmAnalyzer`: "아직 준비되지 않았어요"만 내던 자리를 `video_analyzer.py`로 연결 (모델이 없을 때의 동작과 메시지는 그대로).
- 모델 가중치는 git 제외라 로컬에 둔다: `models/bb_v3.pt`(탐지·추적과 보행자·자전거 신호 둘 다. B 결정: 객체 탐지는 `v8l_bb_v3`가 기본), `models/scene_cls.pt`(M6), `models/crosswalk.pt`(M5). 목록과 sha256은 `backend/models.json`. 환경변수는 `video_analyzer.py` 머리말.
- 탐지·추적은 `imgsz` 960, `conf` 0.15로 돈다(모델을 960으로 학습함, 환경변수 `HMTM_BB_IMGSZ`·`HMTM_BB_CONF`). `bb_kind`(상대 종류 신호)도 기본 960·0.15로 부른다(`HMTM_BB_KIND_IMGSZ`·`HMTM_BB_KIND_CONF`): 서버가 CPU면 전체 추적은 `HMTM_BB_IMGSZ=640`으로 낮추고 사고 직전 2~3초만 보는 `bb_kind`만 960으로 두는 방식이다. 위 "민감도 70%, 오경보 5%" 수치는 `bb_v2`·640으로 잰 것이라 v3·960으로 다시 재야 한다.
- 장면(M6)은 영상 단위 정확도 66.2%(B 평가 기록 v0.26.0)라 늘 추정(guess)으로 내서 사용자에게 확인한다. T자형은 신호 유무를 내지 않는다.
