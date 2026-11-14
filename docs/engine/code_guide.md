# 코드 안내: `run_app.py`를 실행하면 무엇이 불리는가 (+ 6절 서버)

> 2026-10-27 기준. `python run_app.py <영상> --corners "..."` 한 번에 실제로 불리는 파일과 함수만 다룬다.
> 평가 도구(`tools/evaluate/results_table.py` 등)와 학습 코드(`light_cnn.train` 등)는 뺐다.

## 0. 한눈에 보기

```
run_app.py  main()
 └─ src/app/pipeline.py
     ├─ set_scene()  ── make_scene.build_scene() ──────────────▶ scene.json
     │                └ tools/draw_scene.run() ────────────────▶ scene.jpg
     ├─ prepare()    ── camera_check.run() ────────────────────▶ camera.json
     │                ├ stabilize.check() / run() (흔들릴 때) ─▶ stabilized.mp4, stabilize.json
     │                ├ background() ──────────────────────────▶ background.jpg
     │                └ track_video.run()  (YOLO, 가장 오래 걸림) ▶ tracks.json
     └─ solve()      ── stitch_tracks.run() ───────────────────▶ tracks_stitched.json
                      ├ finalize_tracks.run() ─────────────────▶ tracks_final.json
                      ├ tap_track.add() (직접 표시했을 때) ─────▶ tracks_final.json에 추가
                      ├ detect_collision.run() ────────────────▶ collision.json
                      ├ light_states.run() ────────────────────▶ lights.json
                      ├ zone_events.run() ─────────────────────▶ zones.json
                      ├ build_facts.run() ─────────────────────▶ facts.json
                      ├ answers.* (답 검사·가정 만들기)
                      ├ judge_bridge.judge()  → B 판정 모듈 ───▶ result.json
                      └ frames.* (질문 그림) ──────────────────▶ frames/*.jpg, app.json
```

**읽는 법**: 분석 파일(`src/analyze/*.py`)은 거의 다 같은 모양이다.

- `run(...)` 하나가 그 단계의 입구다. 앞 단계가 남긴 JSON을 결과 폴더에서 읽고, 자기 결과를 JSON으로 써 놓는다
- 나머지 `def`는 `run()` 안에서 쓰는 작은 도우미 함수다
- 파일 맨 아래 `if __name__ == "__main__": run()`은 그 파일을 혼자 실행할 때(`python src/analyze/zone_events.py`)만 도는 부분이다. 다른 파일이 `import`할 때는 돌지 않는다
- 단계끼리는 함수 반환값이 아니라 **결과 폴더의 파일로** 이어진다. 그래서 중간 파일을 열어 보면 어느 단계에서 틀렸는지 바로 알 수 있고, 탐지(`tracks.json`)가 있으면 그 뒤만 다시 돌릴 수 있다

좌표는 거의 다 **화면 비율(0~1)**이다. `bbox = [x, y, w, h]`는 박스 왼쪽 위와 너비·높이, `pos = [x, y]`는 박스 **아래 가운데**(차가 땅에 닿은 곳)다.

---

## 1. `run_app.py` (명령)

| 함수 | 하는 일 |
|---|---|
| `main()` | 명령줄 인자(`--corners`, `--answers` 등)를 읽고 `pipeline`의 세 함수를 차례로 부른다. 블랙박스를 골랐으면 `prepare`만 불러 안내하고 끝. 모서리가 있으면 `set_scene` → `prepare` → `solve`. 결과를 사람이 읽기 좋게 출력한다. `InputError`가 나면 한국어 문구만 보여 주고 멈춘다(`SystemExit`) |

## 2. `src/app/pipeline.py` (분석 흐름, 서버와 같이 씀)

| 함수 | 하는 일 |
|---|---|
| `InputError` | 사용자 입력 문제를 뜻하는 예외. `code`(앱이 구분할 이름)와 `message`(사용자에게 보여 줄 한국어)를 갖는다 |
| `load(path)` / `save(obj, path)` | JSON 읽기/쓰기. 한글이 깨지지 않게 `ensure_ascii=False` |
| `stage(name, fn, log)` | `fn()`을 실행하고 걸린 시간을 `log[name]`에 적는다. `app.json`의 `timing_sec`가 여기서 나온다 |
| `analysis_video(case_dir, video)` | 분석에 쓸 영상 경로. 보정 영상(`stabilized.mp4`)이 있으면 그걸, 없으면 원본 |
| `check_video(video)` | 영상 첫 프레임을 읽을 수 있는지. 못 읽으면 `video_unreadable` |
| `unsupported(...)` | `app.json`에 `status: unsupported`와 이유를 쓴다 |
| `background(video, out_path)` | 프레임 15장을 고르게 뽑아 픽셀마다 중앙값을 낸 그림. 지나가는 차는 지워지고 길만 남아서 모서리 찍기에 좋다 |
| `prepare(case_dir, video, source)` | **1단계.** 블랙박스 선택 → 바로 unsupported. 아니면 영상 확인 → 카메라 판단 → 움직이면 보정 가능 여부 확인(안 되면 unsupported) → 보정 → 배경 그림 → 탐지. `tracks.json`이 이미 있으면 건너뜀 |
| `hull_area(pts)` | 네 점을 감싸는 볼록 다각형 넓이. 네 점이 한곳에 몰렸는지 보는 데 씀 |
| `parse_corners(text)` | `"0.3,0.3 0.7,0.3 ..."` 글자를 `[(0.3, 0.3), ...]`로 |
| `set_scene(case_dir, video, corners, closed, frame_ref)` | **2단계.** 모서리 검사(개수·범위·몰림·숫자) → `build_scene`으로 교차로·진입로 영역 → `scene.json`, 확인 그림 `scene.jpg` |
| `check_answers(user)` | 답이 `{}` 모양인지, `user_tracks` 모양이 맞는지 |
| `load_answers(path)` | 답 파일을 읽고 `check_answers`. 파일이 없거나 JSON이 깨졌으면 `InputError` |
| `pair_problem(tracks, pair)` | 사용자가 고른 두 객체로 충돌을 만들 수 없는 이유 (같은 객체 두 번, 없는 번호, 같은 화면에 나온 적 없음) |
| `ask_parties(...)` | 충돌을 못 찾았을 때 `status: no_collision` 응답을 만든다. 움직이는 객체를 한 장면에 번호와 함께 그려서 고르게 함 |
| `solve(case_dir, video, user, judge_dir)` | **3단계.** 아래 순서로 판정까지 하고 `app.json`을 돌려준다 |

`solve()` 안의 순서:

1. `scene.json`, `tracks.json`이 있는지 확인 (없으면 `scene_missing` / `not_prepared`)
2. 직접 표시한 박스 검사, 사용자가 고른 충돌 쌍 꺼내기
3. `stitch` → `finalize` → (직접 표시한 당사자 추적) → 고른 쌍이 말이 되는지(`pair_problem`) → `collision` → 충돌이 없으면 `ask_parties`
4. `lights` → `zones` → `facts`
5. 인정기준의 장(`chapters`)을 보고 보행자·자전거 질문 추가 여부, 답 검사(`answers.check`), 답을 B 가정으로(`to_assumptions`)
6. 답 없는 질문은 모델 추정값으로 채워 판정(`fill_guesses` → `judge_bridge.judge`) → `result.json`
7. 중앙선·도로 폭: 답에 따라 판정이 갈리는지 경우별로 판정해 보고, 같으면 질문 지우기, 다르면 쟁점(`issues`)
8. 질문마다 근거 그림 그리기(`frames.save`, `frames.path_image`)
9. `app.json` 저장

## 3. 1단계에서 불리는 것

### `src/analyze/camera_check.py`: 카메라가 움직이는지

| 함수 | 하는 일 |
|---|---|
| `background_flow(prev, cur)` | 두 프레임 사이의 광류(픽셀이 어느 쪽으로 얼마나 움직였는지)를 계산해 **중앙값**을 낸다. 차 몇 대가 움직여도 화면 대부분(배경)이 가만히 있으면 중앙값은 0에 가깝다 |
| `longest_run(flows)` | 흐름이 `FLOW_MIN`보다 큰 구간이 몇 번 연속됐는지의 최댓값 |
| `decide(flows)` | 연속으로 움직인 구간이 길면 `blackbox`(움직이는 카메라), 모든 구간이 작으면 `cctv`, 그 사이는 `unknown` |
| `run(video, out_dir)` | 5프레임마다 줄인 그림으로 흐름을 재고 판단 → `camera.json` |

### `src/analyze/stabilize.py`: 흔들리는 CCTV 고정

| 함수 | 하는 일 |
|---|---|
| `_match(orb, bf, ka, da, img)` | 첫 프레임의 특징점(ORB)과 이 프레임의 특징점을 짝지어, 이 프레임이 첫 프레임에서 어떻게 틀어졌는지(호모그래피 `H`)와 맞는 점 수를 구한다 |
| `_jump(H, H_prev)` | 새 변환이 앞 프레임 변환과 비교해 화면 귀퉁이를 얼마나 옮기는지. 너무 크면 틀린 변환(큰 차가 화면을 가린 경우)으로 보고 버림 |
| `_aligned(bf, k0, d0, kb, db, H)` | 앞 프레임에 이어 붙여 구한 변환이 맞는지 다시 재는 점수: 첫 화면 특징점을 그 변환으로 옮긴 자리에 이 프레임의 같은 특징점이 있는 수 |
| `unverified_ranges(log)` | 점수가 낮은 프레임이 이어진 구간 (회전·줌하는 CCTV에서 위치를 믿기 어려운 구간) |
| `check(video)` | 영상 전체를 5프레임마다 보며 첫 프레임과 맞는 점 수의 중앙값을 낸다. 35 이상이면 "같은 장면이 흔들리는 것"이라 보정 가능, 아니면 달리는 블랙박스로 봄 |
| `run(video, out_dir)` | 프레임마다 변환을 구해 첫 프레임 자리로 되돌려 그린 `stabilized.mp4`, 프레임별 변환을 `stabilize.json`에 남김 (평가 때 정답 박스도 같은 변환으로 옮김) |

### `src/analyze/track_video.py`: 탐지·추적 (YOLO)

| 함수 | 하는 일 |
|---|---|
| `box_iou(a, b)` | 두 박스가 겹치는 정도 (겹친 넓이 / 합친 넓이) |
| `link_leftovers(left)` | 추적기(ByteTrack)가 쓰지 않고 버린 탐지를 모아, 가까운 것끼리 이어 "조각 궤적"으로 만든다. 들쭉날쭉 잡히는 이륜차·자전거를 살리려는 것 |
| `fill_gaps(frag, fps)` | 조각 안의 빈 프레임을 앞뒤 박스 사이로 선형으로 채움 |
| `run(video, out_dir, stabilized)` | 프레임마다: 화면 전환 검사(`scene_diff`) → YOLO 탐지 → ByteTrack으로 번호 붙이기 → 버려진 탐지 따로 모으기. 끝나면 조각을 붙여 `tracks.json` (궤적 번호 → 프레임별 박스·종류) |
| `scene_diff(a, b)` (run 안) | 아주 작게 줄인 두 그림의 밝기 차 평균 (검은 테두리 제외). 크면 화면 전환. 3프레임 안에 원래 장면으로 돌아오면 잡음으로 보고 넘어감 |

주요 상수: `MODEL`(탐지 모델, `MTM_DETECTOR`로 바꿈), `TO_COCO`(재학습 모델의 종류 이름을 COCO 이름으로), `CONF`(이 점수 이상인 탐지만), `LEFT_*`(조각 잇기 기준).

## 4. 3단계에서 불리는 것

### `src/analyze/stitch_tracks.py`: 끊긴 궤적 잇기

추적기는 차가 잠깐 가려지면 새 번호를 붙인다. 같은 차의 앞뒤 궤적을 하나로 합친다.

| 함수 | 하는 일 |
|---|---|
| `dist(p, q)` | 두 점 사이 거리 |
| `is_static(recs)` | 궤적이 거의 안 움직이는지 (서 있는 차) |
| `is_light(recs)` | 신호등 궤적인지 (신호등과 차는 안 이음) |
| `heading(recs)` | 궤적의 진행 방향(각도). 많이 안 움직였으면 None |
| `turn(a, b)` | 두 방향의 차이(0~180도) |
| `run(out_dir)` | 시작 순서대로 보면서, 앞 궤적의 끝과 이 궤적의 시작이 **가깝고(거리) 짧은 공백 안이고 방향이 크게 안 꺾이면** 붙인다. 조각 궤적(100000번~)은 잇지 않음 → `tracks_stitched.json` |

### `src/analyze/finalize_tracks.py`: 궤적 정리와 종류 정하기

| 함수 | 하는 일 |
|---|---|
| `decide_cls(votes)` | 프레임마다 다르게 잡힌 종류의 다수결. 단, 오토바이·자전거 표가 3표 이상이면 이륜차·자전거로 뒤집음 (작아서 표를 적게 받기 때문). 어떻게 정했는지(`majority` / `two_wheeler_rule`)도 돌려줌 |
| `heights_per_sec(recs, fps)` | 1초에 자기 키의 몇 배를 움직이는지. 사람인데 빠르면 탈것을 탄 사람일 수 있음(`fast_person`) |
| `max_move(recs)` | 시작점에서 가장 멀리 간 거리. 작으면 정지 물체 |
| `interpolate(frames, fps)` | 빠진 프레임을 앞뒤 박스로 채워 프레임이 빠짐없이 이어지게 |
| `run(out_dir)` | 너무 짧은 궤적(15프레임 미만) 버리기 → 종류·움직임·빈칸 채우기 → `tracks_final.json` |

### `src/app/tap_track.py`: 사용자가 직접 표시한 당사자 따라가기 (표시했을 때만)

| 함수 | 하는 일 |
|---|---|
| `check(taps, n_frames)` | 표시한 박스가 규칙에 맞는지 (프레임 범위, 번호 9001~, 종류, 박스가 화면 안) |
| `read_frames(video, last)` | 0~last 프레임을 줄여서 읽기 |
| `hist(img, box)` | 박스 안 색 분포 (MIL 추적기가 엉뚱한 데 붙었는지 볼 때) |
| `new_tracker()` | Vit 추적기 모델 파일이 있으면 Vit, 없으면 MIL |
| `follow(frames, f0, bbox, step)` | 표시한 프레임에서 앞(-1)이나 뒤(+1)로 따라가다 놓치면 멈춤 |
| `make_track(boxes, cls, fps)` | 따라간 박스들을 YOLO 궤적과 같은 모양으로 |
| `add(out_dir, video, taps, n_frames)` | 위를 써서 궤적을 만들어 `tracks_final.json`에 끼워 넣음 |

### `src/analyze/detect_collision.py`: 충돌 찾기

모든 궤적 쌍을 보면서 "떨어져 있다가 → 닿고 → 그 뒤 한쪽이 멈춘" 순간을 충돌로 본다.

| 함수 | 하는 일 |
|---|---|
| `skip_pair(ta, tb)` | 볼 필요 없는 쌍 (신호등이 낌, 둘 다 보행자, 둘 다 서 있음) |
| `has_frag(*tids)` | 조각 궤적(100000번~)이 끼었는지. 조각은 잡음이 많아 순위를 뒤로 |
| `run(out_dir, pair, frame)` | 아래 도우미로 충돌 목록을 만들어 순위대로 정렬 → `collision.json`. 사용자가 쌍을 골랐으면(`pair`) 그 쌍을 충돌로 씀 |

`run()` 안의 도우미:

| 함수 | 하는 일 |
|---|---|
| `area` / `inter` / `contact` | 박스 넓이 / 겹친 넓이 / 작은 박스 대비 겹친 비율 |
| `gap(a, b)` | 두 박스 사이 빈틈 (닿았으면 0) |
| `touching(a, b, f)` | 그 프레임에 닿았는지: 겹침 0.1 이상이거나 빈틈 0.005 이하, 그리고 박스 아래 끝 높이 차이가 작음(화면에서 겹쳐 보이기만 하는 앞뒤 차 제외) |
| `speed(tid, f)` | 5프레임 동안 움직인 거리로 잰 속도 |
| `approach_speed(tid, f0)` | 충돌 전 10프레임 속도의 중앙값 |
| `find_stop(tid, f0, ref)` | 충돌 뒤 20프레임 안에 속도가 접근 속도의 40% 아래로 3프레임 이상 떨어지는 때 |
| `make_event(a, b, f0, confirmed)` | 충돌 하나의 기록 (프레임, 위치, 접근 속도, 둘 다 움직였는지, 멈춘 프레임) |
| `closest(a, b)` | 두 궤적이 가장 가까웠던 프레임 (사용자가 고른 쌍의 충돌 프레임) |
| `candidate()` | 확정 충돌이 하나도 없을 때 "가장 가까이 간 쌍"을 후보로 |
| `born_touch()` | 한쪽이 상대와 닿은 채로 처음 나타난 쌍 (충돌 뒤에야 잡힌 당사자) |

순위: 둘 다 접촉 전에 움직였는지 → 조각이 안 꼈는지 → 이른 시간 순. 맨 앞이 자동으로 고르는 충돌, 앞의 5개가 "부딪힌 두 객체" 질문의 보기.

### `src/analyze/light_states.py`, `light_cnn.py`: 신호등 색 (참고용)

| 함수 | 하는 일 |
|---|---|
| `light_states.run(video, out_dir)` | 신호등 궤적마다 3프레임 간격으로 박스를 조금 넓혀 잘라 색 분류 → `lights.json` |
| `light_states.state_at(states, f)` | f에 가장 가까운 색 기록 |
| `light_cnn.Net` | 작은 CNN (합성곱 3층 → 색 3개: red / green / etc) |
| `light_cnn.prep(img)` | 자른 그림을 세로로 세우고 32×64로 줄여 텐서로 |
| `light_cnn.classify(img)` | 처음 부를 때 모델을 한 번 불러 두고(`_net`), 색과 확률을 돌려줌 |

정확도가 0.70이라 판정에는 안 넣고, 신호 색 질문 옆에 "모델이 본 색"으로만 보여 준다.

### `src/analyze/zone_events.py`: 어느 영역에 있었는지

| 함수 | 하는 일 |
|---|---|
| `poly(pts)` / `inside(pt, p)` | 다각형 만들기 / 점이 다각형 안인지 |
| `zone_of(pt, zones, roi)` | 점이 어느 영역(교차로, 진입로 appr_n 등)에 있는지 |
| `segments(frames, zones, roi)` | 궤적을 "영역 구간" 목록으로: `appr_s(0~40) → intersection(41~80) → appr_n(81~)`. 3프레임 미만으로 튄 구간은 앞 구간에 흡수 |
| `speed_at(frames, f, fps)` | f에서의 속도 |
| `stopped_in(frames, f1, f2, fps)` | 진입 전에, **진입점 가까이에서** 5프레임 이상 멈췄는지 (일시정지) |
| `offset_poly(pts, d)` | 교차로 다각형을 d만큼 넓히거나 좁힘 (모서리를 대충 찍은 오차를 감안해 진입 시점을 범위로 잼) |
| `first_entry(frames, p)` | 밖에 있다가 다각형 안에 처음 들어온 프레임 |
| `intersection_entry(...)` | 교차로에 들어간 순간: 프레임, 어느 진입로에서 왔는지, 어느 진입로로 나갔는지, 진입 속도, 진입 전 정지 |
| `run(scene_path, out_dir)` | 움직이는 궤적(과 당사자)마다 위를 계산 → `zones.json` |

### `src/analyze/build_facts.py`: 판정에 넘길 사실 만들기

| 함수 | 하는 일 |
|---|---|
| `pos_at(tracks, tid, f)` | 그 프레임의 위치 (범위 밖이면 가장 가까운 끝) |
| `heading(tracks, tid, f1, f2)` | f1→f2 이동 벡터 |
| `turn_angle(h1, h2)` | 두 방향 사이 각도 (+는 오른쪽, -는 왼쪽) |
| `movement(deg)` | 각도 → 직진 / 좌회전 / 우회전 / 유턴 |
| `screen_dir(h)` | 화면에서 어느 쪽으로 가는지 (멀어짐 / 다가옴 / 오른쪽 / 왼쪽) |
| `in_poly(pt, poly)` | 점이 다각형 안인지 (반직선을 그어 교차 횟수로) |
| `ray_exit(scene, pos, head, came_from)` | 교차로 안에서 부딪혀 나간 길을 못 봤을 때, 충돌 직전 방향으로 선을 늘려 처음 닿는 진입로로 "나갈 쪽"을 추정 |
| `zone_movement(from_dir, exit_dir)` | 들어온 길·나간 길 → 진행 방향. 예: 남쪽에서 와서 동쪽으로 나가면 우회전 |
| `entry_order(entries, a, b, fps)` | 누가 먼저 교차로에 들어갔는지. 1초 안이면 동시. 모서리 오차 범위로 다시 재도 결과가 같으면 `robust` |
| `unknown_items(...)` | 영상으로 확실히 모르는 것 → 질문 목록 (진행 방향, 온 길, 진입 시점, 종류, 신호등 유무, 부딪힌 쌍) |
| `state_at(states, f)` | 신호등 색 기록 찾기 (light_states와 같은데 torch를 안 불러오려고 따로 둠) |
| `signal_items(parties, light_states, f0)` | 신호 색 질문 (신호등 있다고 답했을 때만 보이게 `depends_on`) |
| `run(out_dir)` | 첫 번째 충돌의 두 당사자마다 종류·온 길·진행 방향·진입 시각·속도를 정리하고, 질문 목록과 도로 정보(교차로 형태, 도로 폭·중앙선 질문)를 붙여 → `facts.json` |

진행 방향은 이 순서로 정한다: 나간 길을 봤으면 `zone_movement`로 확정 → 못 봤으면 `ray_exit`로 추정 → 그것도 안 되면 각도로 추정. 추정이면 `"unknown"`과 추정값(`movement_guess`)을 남기고 질문으로 확인한다.

### `src/app/answers.py`: 사용자 답 다루기

| 함수 | 하는 일 |
|---|---|
| `collision_pair(answers)` | 답에서 "부딪힌 두 객체"를 꺼냄 |
| `check(facts, answers, n_frames)` | 답이 질문의 보기 안인지, 프레임 답이 범위 안인지 |
| `remaining(facts, answers)` | 아직 답이 없는 질문. `depends_on` 조건이 맞을 때만 (예: 신호 색은 신호등 "있음"일 때만) |
| `conflicts(facts, answers)` | 사용자 답이 모델 추정과 다른 질문 (결과 화면에 "영상 분석과 다름" 표시용) |
| `fill_guesses(facts, left, answers)` | 답 없는 질문을 모델 추정값·기본값으로 채운 facts 사본 (답 없이도 판정이 나오게) |
| `to_assumptions(facts, answers)` | 답을 B 판정 모듈이 받는 "가정" 모양으로 (예: 중앙선 있음 → `scene.center_line: true, road_class: general`) |

### `src/app/chapters.py`: 인정기준의 장

| 함수 | 하는 일 |
|---|---|
| `chapter(classes)` | 두 당사자 종류 → 장 (보행자 / 자전거(농기계 포함) / 자동차(이륜차 포함)) |
| `ready(judge_dir, ch)` | 그 장의 도표 파일이 판정 모듈에 있는지 |
| `questions(tid, f0)` | 보행자·자전거 사고용 질문 (부딪힌 곳, 보행자 신호) |

### `src/app/judge_bridge.py`: B 판정 모듈 부르기

| 함수 | 하는 일 |
|---|---|
| `load(judge_dir)` | `../MTM_B/judge`를 파이썬 경로에 넣고 B의 `adapter`, `fault_engine`을 불러옴. 버전도 읽음 |
| `judge(facts_path, assumptions, judge_dir)` | B의 `adapter.to_engine_facts`(A의 facts + 가정 → 엔진 입력) → `fault_engine.judge`(도표 고르기, 기본 비율, 수정요소) → 결과 |

B 쪽 코드(`adapter.py`, `fault_engine.py`, `rules.json`)는 B 브랜치에 있다. A는 이 두 함수 이름과 입력 모양에만 기댄다.

### `src/app/frames.py`: 질문 그림

| 함수 | 하는 일 |
|---|---|
| `draw_box(img, rec, label, color, placed)` | 박스와 `#번호 종류` 이름표를 그림. 이름표끼리 겹치면 아래로 비킴 |
| `save(video, frames, out_dir, tracks, show, parties, cls)` | 근거 프레임마다 당사자(빨강·파랑)와 다른 객체(초록)를 그려 `frames/f00123.jpg`로 |
| `path_image(...)` | 진행 방향·온 길 질문용: 진입로를 색칠하고 보기 이름을 적고, 그 당사자가 지나간 길을 화살표로 → `frames/path_<번호>.jpg` |
| `objects_frame(video, tracks, out_dir)` | 움직이는 객체가 가장 많이 보이는 장면에 모든 객체 번호를 그림 (충돌을 못 찾았을 때 고르는 화면) |

## 5. 2단계에서 불리는 것

### `src/make_scene.py`: 네 모서리 → 영역

| 함수 | 하는 일 |
|---|---|
| `build_scene(corners, video, frame_ref, road_type, closed)` | 네 점을 가운데 기준 각도순으로 정렬해 교차로 다각형을 만들고, 변마다 바깥쪽으로 화면 끝까지 늘려 진입로 4개를 만든다. 변의 가운데가 가장 위면 north, 가장 아래면 south, 나머지 왼쪽·오른쪽이 west·east (화면 기준). 삼거리면 길 없는 쪽(`closed`)은 빼고 3개 |
| `border_pos(p)` | 화면 테두리 위의 점을 시계 방향 거리(0~4)로 (진입로 다각형의 화면 귀퉁이를 넣을 때 씀) |
| `to_border(c, p)` | 가운데 c에서 p 쪽으로 선을 늘려 화면 테두리에 닿는 점 |

### `tools/draw_scene.py`

| 함수 | 하는 일 |
|---|---|
| `to_px(pts, w, h)` | 화면 비율 좌표 → 픽셀 |
| `run(video, scene_path, out_path)` | 기준 프레임에 교차로(노랑)와 진입로(색별)를 반투명으로 칠하고 이름을 적어 저장 (`scene.jpg`, 모서리를 잘 찍었는지 보는 그림) |

---

## 6. 서버 (`src/server/`, 10-29)

앱(안드로이드)은 `run_app.py` 대신 서버를 부른다. 서버는 위 2절의 `prepare` / `set_scene` / `solve`를 그대로 쓴다.

```
[앱] ──HTTP (Authorization: Bearer 토큰)──▶ app.py (API 서버, uvicorn)
                                              │ cases·jobs 표에 쓰고 바로 응답
                                              ▼
                                   data/cases/server.db (SQLite) + data/cases/<id>/ (사건 폴더)
                                              ▲
                                  worker.py (작업자) ── jobs 표에서 꺼내 pipeline 실행
```

**프로세스가 둘이다.** `tools/serve.sh`가 둘 다 띄운다. API 서버만 띄우면 영상을 올려도 `preparing`에서 멈춘다.

| | API 서버 `app.py` | 작업자 `worker.py` |
|---|---|---|
| 하는 일 | 요청 받기, 파일 저장, 상태 응답, 로그인·투표 | 탐지(`prepare`), 판정(`solve`), 오래된 사건 삭제 |
| 속도 | 바로 (모서리 검사 `set_scene`만 여기서 직접, 1초 안쪽) | 작업마다 수 초~수십 초 |
| 서로 주고받는 법 | `jobs` 표에 할 일을 넣음 | `jobs` 표에서 꺼냄 (0.5초마다 확인) |

둘은 직접 대화하지 않고 **같은 DB 파일과 같은 사건 폴더**로만 주고받는다.

### 영상 하나가 지나가는 길

1. `POST /api/cases` → `db.new_case()`(cases 표에 한 줄, 폴더 만들고 `video.mp4` 저장) → `db.add_job(id, "prepare")` → 응답 `preparing`
2. 작업자 `db.take_job()` → `pipeline.prepare()`. 탐지 중 15프레임마다 `progress`를 cases 표에 씀. 끝나면 `prepared = 1`, 모서리가 이미 왔으면 `solve`를 줄에 넣고 아니면 `waiting_scene`
3. `GET /api/cases/{id}` → cases 표의 `status`·`progress` + 사건 폴더의 `app.json`(그림 경로를 서버 주소로 바꿔서)
4. `PUT .../scene` → `pipeline.set_scene()` 바로 실행 → 탐지가 끝났으면 `solve`를 줄에 넣음
5. 작업자 → `pipeline.solve()` → `app.json` → cases `status`를 그 결과 상태로 (`needs_answers` 등)
6. `PUT .../answers` → `answers.json` 저장 → `answer`를 줄에 넣음 → 5번 반복 (여러 번 빨리 보내면 마지막 것만)

### 파일별

| 파일 | 하는 일 |
|---|---|
| `db.py` | 표 7개: `users`, `sessions`, `cases`, `jobs`, `posts`, `votes`, `reports`. `take_job`(작업 꺼내기, 한 사건에 하나만, 판정 작업은 마지막 것만), `expired_cases`(보관 기간 지난 사건) |
| `worker.py` | `run_job`(작업 하나 실행, 입력 오류는 `error`에 남기고 직전 상태로, 그 밖의 오류는 `failed`), `clean_expired`(한 시간마다 지움), `remove_case`(표와 폴더를 같이 지움) |
| `app.py` | API 주소들 (`docs/backend.md` 3절). 모든 주소가 `me()`로 로그인을 확인하고, `own_case()`로 내 사건인지 봄 (남의 것은 없는 것처럼 404) |
| `auth.py` | 로그인. 앱이 보낸 카카오·구글 토큰을 그 회사에 확인(`verify_kakao`, `verify_google`) → 회원 찾기·만들기 → 우리 토큰(`issue`) |
| `posts.py` | 투표글. `snapshot`(올릴 때 결과·사고 설명·그림을 따로 저장), `view`(투표 전에는 AI 결과·집계를 뺌) |

### 로그인 토큰과 `MTM_JWT_SECRET`

로그인하면 앱이 받는 `access`(`eyJ...`)는 JWT다. 점으로 나뉜 세 덩어리: ① 형식 ② 내용(회원 id, 만료 시각) ③ 서명.

- ②는 암호화가 아니라 누구나 풀어 볼 수 있다. 대신 ③이 **②를 비밀 키로 찍은 도장**이라, ②를 바꾸면 도장이 안 맞아 거절된다. 이 비밀 키가 `MTM_JWT_SECRET`이다
- 흐름: `.env`의 `MTM_JWT_SECRET` → `serve.sh`가 환경 변수로 → `auth.py`의 `SECRET` → 로그인 때 `issue()`가 도장을 찍고, 요청마다 `decode()`가 확인
- `.env`에 없으면 서버를 켤 때마다 무작위 키가 새로 생겨서, 재시작하면 받아 둔 토큰이 전부 `token_invalid`가 된다. 그래서 무작위 64글자(`secrets.token_hex(32)`)를 한 번 만들어 `.env`에 고정해 둔다. git에 올리면 안 됨 (누구나 토큰을 만들 수 있게 됨)
- `access`는 30분, `refresh`는 30일. `refresh`는 한 번 쓰면 `sessions` 표에서 지워지고 새것이 나온다

### 설정값이 들어오는 길

`.env` → `tools/serve.sh`가 `. ./.env`로 환경 변수로 만듦 → 각 파일 맨 위 `os.environ.get("이름", 기본값)`

| 이름 | 읽는 파일 | 없을 때 |
|---|---|---|
| `MTM_JWT_SECRET` | `auth.py` | 켤 때마다 무작위 |
| `MTM_DEV_LOGIN` | `auth.py` | 꺼짐 (개발용 로그인 안 됨) |
| `MTM_GOOGLE_CLIENT_IDS` | `auth.py` | 없음 (구글 로그인 안 됨) |
| `MTM_CASES_DIR`, `MTM_DB` | `db.py` | `data/cases`, `data/cases/server.db` |
| `MTM_KEEP_DAYS` | `db.py` | 7 |
| `MTM_MAX_UPLOAD_MB` | `app.py` | 200 |
| `MTM_HIDE_REPORTS` | `posts.py` | 3 |

### 헷갈릴 때 볼 곳

| 궁금한 것 | 볼 곳 |
|---|---|
| 앱이 부르는 주소 | `docs/backend.md` 3절, 서버의 `/docs` |
| 사건 하나에 생긴 파일 | `data/cases/<id>/` |
| 사건·작업 상태 | `data/cases/server.db`의 `cases`, `jobs` 표 |
| 결과·질문 모양 | `docs/app_io.md`, 사건 폴더의 `app.json` |
| 앱 전체 흐름 | `docs/app_flow.md` |

---

## 7. 자주 나오는 문법

| 코드 | 뜻 |
|---|---|
| `stage("tracks", lambda: track_video.run(v, case_dir), log)` | `lambda:`는 "지금 실행하지 말고 나중에 실행할 함수"를 만든다. `stage`가 시간을 재면서 그 안에서 실행한다 |
| `by_tf = {tid: {r["frame"]: r for r in tr["frames"]} for tid, tr in tracks.items()}` | 딕셔너리 안에 딕셔너리를 한 줄로 만드는 것. `by_tf["12"][80]`이면 12번 궤적의 80프레임 기록을 바로 꺼낼 수 있다 (매번 목록을 뒤지지 않게) |
| `next((s for s in segs if ...), None)` | 조건에 맞는 **첫 번째** 것, 없으면 None |
| `dict(user, **{k: v})` | `user`를 복사하면서 `k: v`를 덧붙이거나 바꾼 새 딕셔너리 (원본은 그대로) |
| `{f0: b, **follow(...), **follow(...)}` | 딕셔너리 여러 개를 하나로 합침 |
| `for ... : ... break` 다음 `else:` | 반복문이 `break` 없이 끝까지 돌았을 때만 `else`가 실행된다 |
| `x if cond else y` | 조건이 참이면 x, 아니면 y |
| `round(v, 4)` | JSON을 작게 하려고 소수 넷째 자리까지만 |
| `os.environ.get("MTM_DETECTOR", "models/yolov8s.pt")` | 환경 변수가 있으면 그 값, 없으면 기본값 |
| `if __name__ == "__main__":` | 파일을 직접 실행할 때만 도는 부분 (import할 때는 안 돎) |
| `raise InputError("corners_count", "...")` | 여기서 멈추고 오류를 위로 던진다. 받는 쪽(`run_app.py`, 서버)이 `except InputError`로 잡아 안내로 바꾼다 |
