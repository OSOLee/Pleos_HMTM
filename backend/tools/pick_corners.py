"""교차로 네 모서리를 클릭으로 찍어 scenes/cc_<날짜>_corners.json을 만드는 로컬 페이지

  python tools/pick_corners.py cc_3_180420_vehicle_21_264 cc_3_160316_vehicle_210_47971 ...
  → 브라우저에서 http://localhost:8765 열기
  python tools/pick_corners.py --out outputs/demo_scenes cc_3_180420_vehicle_21_264
  → 저장 폴더를 바꿈 (보여 주기용. 평가에 쓰는 scenes/를 덮지 않게)

앱에서 사용자가 하는 일(첫 장면에서 네 모서리 누르기, 삼거리면 길 없는 쪽 고르기)을 그대로 흉내 낸다.
교차로가 차에 가려지지 않게 기본 그림은 지나가는 차를 지운 배경(프레임 중앙값)이고, 슬라이더로 프레임을 고를 수도 있다.
고정 카메라라 어느 그림에서 찍어도 좌표는 같다.
영상은 밖으로 나가지 않는다 (127.0.0.1에서만 열림). 저장하면 make_scene.build_scene으로 장면을 만들고
영역을 겹친 그림(tools/draw_scene)을 바로 보여 준다.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

import cv2
import numpy as np

sys.path.insert(0, os.getcwd())
from src.make_scene import build_scene
from tools import draw_scene

PORT = 8765
VIDEO_DIR = "data/videos/cc"
STABILIZED_DIRS = ["outputs/eval_auto", "outputs/eval_signal_auto"]   # 보정 영상을 찾을 결과 폴더

PAGE = """<!doctype html><meta charset="utf-8"><title>모서리 찍기</title>
<style>
body{font-family:sans-serif;margin:16px;background:#f6f6f6}
#wrap{position:relative;display:inline-block}
img{max-width:100%;display:block}
canvas{position:absolute;left:0;top:0}
button{margin:2px;padding:6px 12px;font-size:15px}
.on{background:#222;color:#fff}
#list button.done{background:#cfc}
</style>
<div id="list"></div>
<h3 id="title"></h3>
<div>사고 난 곳:
 <button data-p="intersection" class="on">교차로</button><button data-p="roundabout">회전교차로</button>
 <button data-p="parking_lot">주차장</button><button data-p="straight">교차로 아닌 길</button></div>
<p id="guide"></p>
<div>그림: <button id="bg" class="on">배경 (지나가는 차 지움)</button>
 프레임 <input type="range" id="fr" min="0" max="149" value="0" style="width:40%"> <span id="frn"></span></div>
<div id="shape">교차로 형태:
 <button id="cross" class="on">사거리</button>
 <div style="margin-left:2em">삼거리면 길 없는 쪽:
 <button data-c="north">위</button><button data-c="east">오른쪽</button>
 <button data-c="south">아래</button><button data-c="west">왼쪽</button></div></div>
<div><button id="clear">지우기</button> <button id="save">저장</button> <span id="msg"></span></div>
<div id="wrap"><img id="img"><canvas id="cv"></canvas></div>
<h4>저장한 장면 (교차로 노랑, 진입로 색별)</h4><img id="scene" style="max-width:100%">
<script>
const videos = VIDEOS;
let cur = 0, pts = [], closed = null, place = 'intersection';
// 장소마다 네 점을 어디에 찍는지 (src/app/pipeline.set_scene의 place). 회전 차로·주차 칸 같은 건 나중에 질문으로 받음
const GUIDE = {
  intersection: '교차로 네 모서리를 누르세요 (연석이나 횡단보도 안쪽 끝이 만나는 곳, 순서 상관없음).',
  roundabout: '회전교차로를 둘러싼 네 점을 누르세요 (가운데 섬과 회전 차로가 다 들어가게).',
  parking_lot: '사고 난 주차장 통로 둘레의 네 점을 누르세요 (두 차가 다 들어가게).',
  straight: '사고 난 길 구간의 네 점을 누르세요 (길 양쪽 가장자리, 두 차가 다 들어가게).'};
function setPlace(p) { place = p;
  document.querySelectorAll('[data-p]').forEach(b => b.className = b.dataset.p === p ? 'on' : '');
  document.getElementById('shape').style.display = p === 'intersection' ? '' : 'none';
  if (p !== 'intersection') setClosed(null);
  document.getElementById('guide').textContent = GUIDE[p] + ' 다시 찍으려면 [지우기]. 저장한 적이 있으면 그 점이 처음부터 찍혀 있어요.'; }
document.querySelectorAll('[data-p]').forEach(b => b.onclick = () => setPlace(b.dataset.p));
const img = document.getElementById('img'), cv = document.getElementById('cv'), ctx = cv.getContext('2d');
function list(done) {
  const l = document.getElementById('list'); l.innerHTML = '';
  videos.forEach((v, i) => { const b = document.createElement('button'); b.textContent = v.slice(5, 11);
    if (done && done.includes(v)) b.className = 'done'; if (i === cur) b.style.fontWeight = 'bold';
    b.onclick = () => load(i); l.appendChild(b); });
}
const fr = document.getElementById('fr'), bgb = document.getElementById('bg');
function show(bg) {   // bg: 차를 지운 배경 그림, 아니면 슬라이더의 프레임
  bgb.className = bg ? 'on' : '';
  document.getElementById('frn').textContent = bg ? '' : fr.value + '프레임';
  img.src = '/frame/' + videos[cur] + (bg ? '?bg=1' : '?f=' + fr.value) + '&t=' + Date.now();
}
bgb.onclick = () => show(true);
fr.oninput = () => show(false);
function load(i) {
  cur = i; pts = []; setClosed(null); setPlace('intersection');
  document.getElementById('title').textContent = videos[i];
  fetch('/info/' + videos[i]).then(r => r.json()).then(j => {
    fr.max = j.frames - 1; fr.value = 0;
    if (j.corners) { pts = j.corners; setPlace(j.place); setClosed(j.closed); }
    show(true);
  });
  document.getElementById('scene').src = '/scene/' + videos[i] + '?t=' + Date.now();
  document.getElementById('msg').textContent = '';
  fetch('/done').then(r => r.json()).then(list);
}
img.onload = () => { cv.width = img.clientWidth; cv.height = img.clientHeight; draw(); };
function draw() {
  ctx.clearRect(0, 0, cv.width, cv.height);
  ctx.fillStyle = 'red'; ctx.strokeStyle = 'yellow'; ctx.lineWidth = 2;
  pts.forEach(p => { ctx.beginPath(); ctx.arc(p[0] * cv.width, p[1] * cv.height, 6, 0, 7); ctx.fill(); });
  if (pts.length === 4) {
    const c = pts.reduce((a, p) => [a[0] + p[0] / 4, a[1] + p[1] / 4], [0, 0]);
    const s = [...pts].sort((a, b) => Math.atan2(a[1] - c[1], a[0] - c[0]) - Math.atan2(b[1] - c[1], b[0] - c[0]));
    ctx.beginPath(); s.forEach((p, k) => (k ? ctx.lineTo : ctx.moveTo).call(ctx, p[0] * cv.width, p[1] * cv.height));
    ctx.closePath(); ctx.stroke();
  }
}
cv.onclick = e => { if (pts.length >= 4) return; const r = cv.getBoundingClientRect();
  pts.push([+((e.clientX - r.left) / r.width).toFixed(4), +((e.clientY - r.top) / r.height).toFixed(4)]); draw(); };
function setClosed(c) { closed = c;
  document.querySelectorAll('[data-c]').forEach(b => b.className = b.dataset.c === c ? 'on' : '');
  document.getElementById('cross').className = c ? '' : 'on'; }
document.querySelectorAll('[data-c]').forEach(b => b.onclick = () => setClosed(b.dataset.c));
document.getElementById('cross').onclick = () => setClosed(null);
document.getElementById('clear').onclick = () => { pts = []; draw(); };
document.getElementById('save').onclick = () => {
  if (pts.length !== 4) { document.getElementById('msg').textContent = '모서리 4개를 찍어 주세요'; return; }
  fetch('/save', {method: 'POST', body: JSON.stringify({video: videos[cur], corners: pts, closed, place})})
    .then(r => r.json()).then(j => { document.getElementById('msg').textContent = '저장: ' + j.path;
      document.getElementById('scene').src = '/scene/' + videos[cur] + '?t=' + Date.now();
      fetch('/done').then(r => r.json()).then(list); });
};
load(0);
</script>"""


SCENE_DIR = "scenes"   # --out으로 바꿈


def scene_path(name):
    return os.path.join(SCENE_DIR, f"cc_{name.split('_')[2]}_corners.json")


def video_path(name):
    """보여 줄 영상. 흔들리는 CCTV는 결과 폴더의 보정 영상(stabilize.py)을 쓴다. 보정 영상은 첫 프레임에
    맞춰져 있어 좌표가 원본 첫 프레임과 같고, 배경 그림·슬라이더 어느 프레임에서 찍어도 같다"""
    for d in STABILIZED_DIRS:
        p = os.path.join(d, name, "stabilized.mp4")
        if os.path.exists(p):
            return p
    return os.path.join(VIDEO_DIR, name + ".mp4")


def frame_jpg(name, frame=0):
    cap = cv2.VideoCapture(video_path(name))
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
    ok, img = cap.read()
    cap.release()
    return cv2.imencode(".jpg", img)[1].tobytes() if ok else b""


BG_FRAMES = 15   # 배경 그림을 만들 때 고르게 뽑는 프레임 수
_bg = {}


def background_jpg(name):
    """프레임 BG_FRAMES장의 픽셀별 중앙값. 지나가는 차가 지워져 교차로가 가려지지 않는다 (서 있는 차는 남음)"""
    if name not in _bg:
        cap = cv2.VideoCapture(video_path(name))
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        imgs = []
        for k in range(BG_FRAMES):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(k * (n - 1) / (BG_FRAMES - 1)))
            ok, img = cap.read()
            if ok:
                imgs.append(img)
        cap.release()
        _bg[name] = cv2.imencode(".jpg", np.median(np.stack(imgs), axis=0).astype(np.uint8))[1].tobytes()
    return _bg[name]


def info(name):
    """프레임 수, 저장한 적이 있으면 그 모서리, 길 없는 쪽, 장소 종류"""
    cap = cv2.VideoCapture(video_path(name))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    out = {"frames": n, "corners": None, "closed": None, "place": "intersection"}
    if os.path.exists(scene_path(name)):
        with open(scene_path(name), encoding="utf-8") as f:
            s = json.load(f)
        out["corners"], out["closed"] = s.get("corners"), s.get("closed_side")
        out["place"] = s.get("road_type") or "intersection"
    return out


class Handler(BaseHTTPRequestHandler):
    videos = []

    def send(self, body, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            self.send(PAGE.replace("VIDEOS", json.dumps(self.videos)).encode(), "text/html; charset=utf-8")
        elif path == "/done":
            self.send(json.dumps([v for v in self.videos if os.path.exists(scene_path(v))]).encode(),
                      "application/json")
        elif path.startswith("/info/"):
            self.send(json.dumps(info(path[6:])).encode(), "application/json")
        elif path.startswith("/frame/"):
            query = dict(kv.split("=") for kv in self.path.split("?", 1)[1].split("&")) if "?" in self.path else {}
            if query.get("bg"):
                self.send(background_jpg(path[7:]), "image/jpeg")
            else:
                self.send(frame_jpg(path[7:], int(query.get("f", 0))), "image/jpeg")
        elif path.startswith("/scene/"):
            name = path[7:]
            out = f"/tmp/pick_{name}.jpg"
            if os.path.exists(scene_path(name)):
                draw_scene.run(video_path(name), scene_path(name), out)
                self.send(open(out, "rb").read(), "image/jpeg")
            else:
                self.send(b"", "image/jpeg")
        else:
            self.send_error(404)

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        place = req.get("place") or "intersection"
        scene = build_scene([tuple(p) for p in req["corners"]], os.path.join(VIDEO_DIR, req["video"] + ".mp4"),
                            road_type=place, closed=req["closed"] if place == "intersection" else None)
        os.makedirs(SCENE_DIR, exist_ok=True)
        with open(scene_path(req["video"]), "w", encoding="utf-8") as f:
            json.dump(scene, f, ensure_ascii=False, indent=1)
        print(f"저장: {scene_path(req['video'])} (장소 {place}, 형태 {scene['junction_type']}, 길 없는 쪽 {req['closed']})")
        self.send(json.dumps({"path": scene_path(req["video"])}).encode(), "application/json")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--out" in args:
        k = args.index("--out")
        SCENE_DIR = args[k + 1]
        del args[k:k + 2]
    Handler.videos = args
    print(f"http://localhost:{PORT} 에서 {len(Handler.videos)}개 영상 모서리 찍기 (끝내려면 Ctrl+C)")
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
