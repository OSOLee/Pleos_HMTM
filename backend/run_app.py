"""앱 프로토타입: 영상 + 교차로 네 모서리 (+ 사용자 답) -> facts.json -> B 판정 -> app.json

처음 실행 (질문 받기):
  python run_app.py data/videos/cc/<영상>.mp4 --corners "x,y x,y x,y x,y"
사용자 답 반영 (YOLO는 다시 안 돌림):
  python run_app.py data/videos/cc/<영상>.mp4 --answers answers.json

결과 폴더(기본 outputs/app/<영상 이름>)의 app.json이 앱에 넘길 응답이다.
분석 단계는 src/app/pipeline.py (prepare / set_scene / solve)에 있고, 이 파일은 그 셋을 차례로 부르는 명령이다.
서버도 같은 함수를 쓴다 (docs/backend.md).
"""
import argparse
import os

from src.app import pipeline
from src.app.pipeline import InputError


def main():
    ap = argparse.ArgumentParser(description="앱 프로토타입: 영상 -> 질문 -> 판정")
    ap.add_argument("video")
    ap.add_argument("--source", choices=["cctv", "blackbox"], default="cctv",
                    help="사용자가 홈 화면에서 고른 영상 종류. 블랙박스는 아직 분석하지 않음")
    ap.add_argument("--corners", help='교차로 네 모서리 "x,y x,y x,y x,y" (0~1). 처음 실행 때 필요')
    ap.add_argument("--frame-ref", type=int, default=0, help="모서리를 찍은 프레임")
    ap.add_argument("--closed", choices=["north", "east", "south", "west"],
                    help="삼거리(T자형)면 길이 없는 쪽 (화면 기준). 없으면 사거리")
    ap.add_argument("--place", choices=["intersection", "roundabout", "parking_lot", "straight"], default="intersection",
                    help="장소 종류 (교차로 / 회전교차로 / 주차장 / 교차로 아닌 길). 모서리와 같이 처음 실행 때")
    ap.add_argument("--answers", help="사용자 답 JSON (unknowns의 field -> 값)")
    ap.add_argument("--out", help="결과 폴더 (기본 outputs/app/<영상 이름>)")
    ap.add_argument("--judge", default=pipeline.JUDGE_DIR, help="B 판정 모듈 폴더")
    args = ap.parse_args()

    name = os.path.splitext(os.path.basename(args.video))[0]
    out = args.out or os.path.join("outputs", "app", name)
    os.makedirs(out, exist_ok=True)
    log = {}
    try:
        # 블랙박스를 골랐으면 모서리 없이 바로 안내 (prepare가 app.json에 unsupported를 남김)
        if args.source == "blackbox":
            pipeline.prepare(out, args.video, args.source, name, log)
            raise SystemExit("블랙박스를 골라서 중단")
        # 모서리는 무거운 분석 전에 검사 (잘못 찍었으면 바로 안내)
        if args.corners:
            pipeline.set_scene(out, args.video, pipeline.parse_corners(args.corners), args.closed, args.frame_ref,
                               args.place)
        elif not os.path.exists(os.path.join(out, "scene.json")):
            raise SystemExit("처음 실행에는 --corners가 필요해요")
        user = pipeline.load_answers(args.answers) if args.answers else {}
        if pipeline.prepare(out, args.video, args.source, name, log) == "unsupported":
            raise SystemExit(pipeline.load(os.path.join(out, "app.json"))["message"])
        app = pipeline.solve(out, args.video, user, args.judge, name, log)
    except InputError as e:
        raise SystemExit(e.message)

    print(f"\n=== {name} ===")
    if app["status"] == "no_collision":
        objs = app["questions"][0]["objects"]
        print(f"{app['message']}\n객체 {len(objs)}개, 장면 {app['questions'][0]['image']}. "
              "answers에 collision.parties(두 id) 또는 user_tracks(직접 표시)를 넣어 다시 실행")
        return
    v = app["verdict"]
    print(f"상태: {app['status']} | 판정: {v['status']} {v['rule_id']} {v['fault_by_track']}"
          + (f" (추정값 사용: {v['auto_filled']})" if v["auto_filled"] else ""))
    if v["notice"]:
        print(f"  알림: {v['notice']}")
    for iss in app["issues"]:
        print(f"  쟁점 {iss['field']}: " + " / ".join(f"{c['choice']} → {c['rule_id']} {c['fault_by_track']}" for c in iss["cases"]))
    for u in app["questions"]:
        print(f"  질문 {u['field']}: {u['question']} {u.get('choices')} (근거 {u['image']})")
    print(f"시간(초): {log}")
    print(f"저장: {os.path.join(out, 'app.json')}")


if __name__ == "__main__":
    main()
