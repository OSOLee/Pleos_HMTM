"""앱 API 시험 (src/server). 작업자는 띄우지 않고 worker.run_once()로 작업을 하나씩 직접 돌림

  python -m unittest tests.test_api              # 탐지 결과를 미리 넣어 탐지는 건너뜀 (10초 안쪽)
  MTM_SLOW=1 python -m unittest tests.test_api   # 탐지부터 (1분 안팎)

로그인은 카카오·구글 대신 시험용 확인 함수(토큰 = 이름)로 바꿔 끼움.
평가 영상(data/videos)과 평가 결과(outputs/eval_auto)가 있어야 함. 없으면 건너뜀.
"""
import contextlib
import io
import os
import shutil
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)   # 모델 경로 등이 backend 폴더 기준 (판정 모듈은 backend/judge)
from fastapi.testclient import TestClient

from src.app import pipeline
from src.server import app as server, auth, db, worker

NAME = "cc_3_211208_vehicle_120_011"
VIDEO = os.path.join(ROOT, "data/videos/cc", NAME + ".mp4")
AUTO = os.path.join(ROOT, "outputs/eval_auto", NAME)
SLOW = os.environ.get("MTM_SLOW") == "1"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mtm_api_")
        self._old = db.CASES_DIR, db.DB_PATH, dict(auth.VERIFIERS)
        db.CASES_DIR, db.DB_PATH = self.tmp, os.path.join(self.tmp, "server.db")
        auth.VERIFIERS["kakao"] = lambda token: "kakao-" + token   # 카카오에 묻는 대신
        self.c = TestClient(server.app)

    def tearDown(self):
        db.CASES_DIR, db.DB_PATH, verifiers = self._old
        auth.VERIFIERS.clear()
        auth.VERIFIERS.update(verifiers)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def login(self, name, signup=True):
        """로그인(+ 가입) → Authorization 헤더"""
        r = self.c.post("/api/auth/kakao", json={"token": name}).json()
        h = {"Authorization": "Bearer " + r["access"]}
        if signup:
            self.c.put("/api/me", json={"nickname": name, "agree_terms": True}, headers=h)
        return h

    def work(self):
        """쌓인 작업을 다 돌림"""
        with contextlib.redirect_stdout(io.StringIO()):
            while worker.run_once():
                pass


class Auth(Base):
    def test_login_signup_refresh(self):
        r = self.c.post("/api/auth/kakao", json={"token": "kim"}).json()
        self.assertTrue(r["user"]["needs_signup"])
        h = {"Authorization": "Bearer " + r["access"]}
        self.assertEqual(self.c.get("/api/me/cases", headers=h).json()["error"], "signup_required")
        self.assertEqual(self.c.put("/api/me", json={"nickname": "a"}, headers=h).json()["error"], "nickname_length")
        me = self.c.put("/api/me", json={"nickname": "김철수", "agree_terms": True}, headers=h).json()
        self.assertFalse(me["needs_signup"])
        self.assertFalse(me["train_consent"])
        self.assertTrue(self.c.put("/api/me", json={"train_consent": True}, headers=h).json()["train_consent"])
        self.assertEqual(self.c.get("/api/me/cases", headers=h).json(), [])
        # 같은 카카오 계정으로 다시 로그인하면 같은 회원
        again = self.c.post("/api/auth/kakao", json={"token": "kim"}).json()
        self.assertEqual(again["user"]["id"], me["id"])
        # 다른 사람이 같은 닉네임은 못 씀
        h2 = self.login("lee", signup=False)
        self.assertEqual(self.c.put("/api/me", json={"nickname": "김철수"}, headers=h2).json()["error"], "nickname_taken")
        # refresh는 한 번만 쓸 수 있음 (쓰면 새것으로 바뀜)
        new = self.c.post("/api/token/refresh", json={"refresh": r["refresh"]})
        self.assertEqual(new.status_code, 200)
        self.assertEqual(self.c.post("/api/token/refresh", json={"refresh": r["refresh"]}).json()["error"], "token_invalid")
        self.c.post("/api/token/logout", json={"refresh": new.json()["refresh"]})
        self.assertEqual(self.c.post("/api/token/refresh", json={"refresh": new.json()["refresh"]}).status_code, 401)

    def test_kakao_token_must_be_ours(self):
        """카카오 토큰 정보의 app_id가 우리 앱 ID와 같아야 로그인 (다른 앱에서 받은 토큰은 거절)"""
        class Resp:
            def __init__(self, body):
                self.status_code, self.body = 200, body

            def json(self):
                return self.body

        old = auth.KAKAO_APP_ID, auth.httpx.get
        try:
            auth.KAKAO_APP_ID = "1627628"
            auth.httpx.get = lambda *a, **k: Resp({"id": 42, "app_id": 1627628})
            self.assertEqual(auth.verify_kakao("t"), "42")
            auth.httpx.get = lambda *a, **k: Resp({"id": 42, "app_id": 999})
            with self.assertRaises(auth.AuthError) as e:
                auth.verify_kakao("t")
            self.assertEqual(e.exception.code, "provider_token_invalid")
            auth.KAKAO_APP_ID = ""
            with self.assertRaises(auth.AuthError) as e:
                auth.verify_kakao("t")
            self.assertEqual(e.exception.code, "provider_not_configured")
        finally:
            auth.KAKAO_APP_ID, auth.httpx.get = old

    def test_errors(self):
        self.assertEqual(self.c.get("/api/me").json()["error"], "login_required")
        self.assertEqual(self.c.get("/api/me", headers={"Authorization": "Bearer x"}).json()["error"], "token_invalid")
        self.assertEqual(self.c.post("/api/auth/naver", json={"token": "x"}).status_code, 404)
        self.assertEqual(self.c.post("/api/auth/dev", json={"token": "x"}).status_code, 404)   # 개발용 로그인은 꺼져 있음


@unittest.skipUnless(os.path.exists(VIDEO) and os.path.isdir(AUTO), "평가 영상·결과가 없음")
class Cases(Base):
    def setUp(self):
        super().setUp()
        self.h = self.login("kim")

    def upload(self, source="cctv", h=None):
        with open(VIDEO, "rb") as f:
            r = self.c.post("/api/cases", files={"video": (NAME + ".mp4", f, "video/mp4")}, data={"source": source},
                            headers=h or self.h)
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def skip_detection(self, cid):
        """평가 때 저장한 탐지 결과를 넣어 prepare가 탐지를 건너뛰게 함 (빠른 시험)"""
        for n in ("camera.json", "tracks.json"):
            shutil.copy(os.path.join(AUTO, n), os.path.join(db.case_dir(cid), n))

    def scene_body(self):
        s = pipeline.load(os.path.join(AUTO, "scene.json"))
        return {"corners": s["corners"], "closed": s.get("closed_side")}

    def analyzed(self):
        """올리기 → 모서리 → 판정까지 한 사건"""
        cid = self.upload()["id"]
        if not SLOW:
            self.skip_detection(cid)
        self.c.put(f"/api/cases/{cid}/scene", json=self.scene_body(), headers=self.h)
        self.work()
        return cid

    def test_flow_upload_scene_answers(self):
        case = self.upload()
        cid = case["id"]
        self.assertEqual((case["status"], case["saved"]), ("preparing", False))
        self.assertIsNotNone(case["delete_at"])   # 저장 안 하면 7일 뒤 지워짐
        if not SLOW:
            self.skip_detection(cid)
        # 탐지 전에 모서리부터 와도 됨 → 준비가 끝나면 바로 판정
        r = self.c.put(f"/api/cases/{cid}/scene", json=self.scene_body(), headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "preparing")
        self.assertTrue(r.json()["scene_image"].endswith("/scene.jpg"))
        self.work()
        got = self.c.get(f"/api/cases/{cid}", headers=self.h).json()
        self.assertEqual(got["progress"], 100)
        saved = pipeline.load(os.path.join(AUTO, "app.json"))
        self.assertEqual(got["status"], saved["status"])
        for k in ("rule_id", "fault_by_track"):
            self.assertEqual(got["result"]["verdict"][k], saved["verdict"][k])
        # 그림 경로가 서버 주소로 바뀌고, 그 주소로 받을 수 있음 (로그인 필요)
        img = got["result"]["collision"]["image"]
        self.assertTrue(img.startswith(f"/api/cases/{cid}/files/"))
        self.assertEqual(self.c.get(img, headers=self.h).status_code, 200)
        self.assertEqual(self.c.get(img).status_code, 401)

        # 답 두 번을 빨리 보내면 마지막 것만 돌림
        self.c.put(f"/api/cases/{cid}/answers", json={"road.signal_present": True}, headers=self.h)
        r = self.c.put(f"/api/cases/{cid}/answers", json={"road.signal_present": False}, headers=self.h)
        self.assertEqual(r.json()["status"], "analyzing")
        self.work()
        got = self.c.get(f"/api/cases/{cid}", headers=self.h).json()
        self.assertEqual(got["result"]["answers"], {"road.signal_present": False})
        self.assertNotIn("road.signal_present", [q["field"] for q in got["result"]["questions"]])

        # 보기에 없는 답 → 사건에 오류로 남고 직전 결과 상태로 돌아감
        self.c.put(f"/api/cases/{cid}/answers", json={"road.signal_present": "maybe"}, headers=self.h)
        self.work()
        got = self.c.get(f"/api/cases/{cid}", headers=self.h).json()
        self.assertEqual(got["error"]["error"], "answer_invalid")
        self.assertIn(got["status"], ("needs_answers", "done"))

        # 남의 사건은 없는 것처럼
        other = self.login("lee")
        self.assertEqual(self.c.get(f"/api/cases/{cid}", headers=other).json()["error"], "case_not_found")

        self.assertEqual(self.c.delete(f"/api/cases/{cid}", headers=self.h).status_code, 204)
        self.assertEqual(self.c.get(f"/api/cases/{cid}", headers=self.h).status_code, 404)
        self.assertFalse(os.path.exists(db.case_dir(cid)))

    def test_errors(self):
        cid = self.upload()["id"]
        r = self.c.put(f"/api/cases/{cid}/scene", json={"corners": [[0.5, 0.5]] * 4}, headers=self.h)
        self.assertEqual((r.status_code, r.json()["error"]), (422, "corners_too_close"))
        r = self.c.put(f"/api/cases/{cid}/answers", json={}, headers=self.h)
        self.assertEqual((r.status_code, r.json()["error"]), (409, "not_ready"))
        self.assertEqual(self.c.get(f"/api/cases/{cid}/background.jpg", headers=self.h).json()["error"], "not_ready")
        self.assertEqual(self.c.get(f"/api/cases/{cid}/files/../server.db", headers=self.h).status_code, 404)
        self.assertEqual(self.c.get(f"/api/cases/{cid}/files/video.mp4", headers=self.h).status_code, 404)
        self.assertEqual(self.c.get(f"/api/cases/{cid}/frames/10.jpg", headers=self.h).status_code, 200)
        self.assertEqual(self.c.get(f"/api/cases/{cid}/frames/99999.jpg", headers=self.h).json()["error"], "frame_range")
        r = self.c.post("/api/cases", files={"video": ("x.mp4", b"not a video", "video/mp4")}, headers=self.h)
        self.assertEqual((r.status_code, r.json()["error"]), (422, "video_unreadable"))
        self.assertEqual(self.c.post("/api/cases", files={"video": ("x.mp4", b"x", "video/mp4")}).status_code, 401)

    def test_evidence_and_summary(self):
        """근거 화면 데이터(두 당사자 궤적·사건 기록·영상 크기)와 기록 목록의 판정 요약"""
        before = self.upload()["id"]
        self.assertEqual(self.c.get(f"/api/cases/{before}/evidence", headers=self.h).json()["error"], "not_ready")
        cid = self.analyzed()
        ev = self.c.get(f"/api/cases/{cid}/evidence", headers=self.h).json()
        app = pipeline.load(os.path.join(db.case_dir(cid), "app.json"))
        self.assertEqual([t["id"] for t in ev["tracks"]], [app["collision"]["a"], app["collision"]["b"]])
        self.assertEqual((ev["width"], ev["height"]), (1920, 1080))
        self.assertIn("collision", [e["type"] for e in ev["events"]])
        self.assertEqual([e["t"] for e in ev["events"]], sorted(e["t"] for e in ev["events"]))   # 시간 순
        self.assertEqual(len(ev["tracks"][0]["frames"][0]["box"]), 4)
        listed = {c["id"]: c for c in self.c.get("/api/me/cases", headers=self.h).json()}
        self.assertEqual(listed[cid]["summary"]["rule_id"], app["verdict"]["rule_id"])
        self.assertIsNone(listed[cid]["result"])   # 목록엔 결과 전체는 빼고 요약만
        self.assertIsNone(listed[before]["summary"])

    def test_blackbox_is_unsupported(self):
        case = self.upload("blackbox")
        self.assertEqual(case["status"], "unsupported")
        self.assertEqual(case["result"]["reason"], "blackbox_selected")

    def test_save_and_expire(self):
        keep, drop = self.upload()["id"], self.upload()["id"]
        r = self.c.put(f"/api/cases/{keep}/save", json={"saved": True}, headers=self.h).json()
        self.assertEqual((r["saved"], r["delete_at"]), (True, None))
        self.assertEqual(len(self.c.get("/api/me/cases", headers=self.h).json()), 2)
        self.assertEqual(worker.clean_expired(now=time.time() + 8 * 86400), 1)   # 8일 뒤: 저장 안 한 것만 지움
        self.assertEqual([c["id"] for c in self.c.get("/api/me/cases", headers=self.h).json()], [keep])
        self.assertFalse(os.path.exists(db.case_dir(drop)))

    def test_posts_and_votes(self):
        cid = self.analyzed()
        r = self.c.post("/api/posts", json={"case_id": cid, "title": "누가 잘못?"}, headers=self.h)
        self.assertEqual(r.json()["error"], "case_not_done")
        db.update_case(cid, status="done")   # 질문에 다 답한 것으로 (시험을 짧게)
        r = self.c.post("/api/posts", json={"case_id": cid, "title": "누가 잘못?"}, headers=self.h)
        self.assertEqual(r.json()["error"], "case_not_saved")
        self.c.put(f"/api/cases/{cid}/save", json={"saved": True}, headers=self.h)
        r = self.c.post("/api/posts", json={"case_id": cid, "title": "누가 잘못?", "visibility": "video"}, headers=self.h)
        self.assertEqual(r.json()["error"], "visibility_unsupported")
        post = self.c.post("/api/posts", json={"case_id": cid, "title": "누가 잘못?"}, headers=self.h).json()
        pid = post["id"]
        self.assertIn("ai", post)   # 글쓴이는 AI 결과를 봄
        self.assertEqual(self.c.post("/api/posts", json={"case_id": cid, "title": "또"}, headers=self.h).json()["error"],
                         "post_exists")
        self.assertEqual(self.c.put(f"/api/cases/{cid}/save", json={"saved": False}, headers=self.h).json()["error"],
                         "has_post")
        self.assertEqual(self.c.get(post["collision_image"], headers=self.h).status_code, 200)

        # 다른 회원: 투표 전에는 AI 결과·집계가 안 보이고, 투표하면 보임
        lee = self.login("lee")
        self.assertEqual([p["id"] for p in self.c.get("/api/posts", headers=lee).json()], [pid])
        seen = self.c.get(f"/api/posts/{pid}", headers=lee).json()
        self.assertNotIn("ai", seen)
        self.assertEqual(set(seen["parties"]), {"A", "B"})
        self.assertEqual(self.c.put(f"/api/posts/{pid}/vote", json={"a_ratio": 35}, headers=lee).json()["error"],
                         "ratio_invalid")
        voted = self.c.put(f"/api/posts/{pid}/vote", json={"a_ratio": 30}, headers=lee).json()
        self.assertEqual(voted["ai"]["fault"]["A"], post["ai"]["fault"]["A"])
        self.assertEqual((voted["votes"]["count"], voted["votes"]["a_avg"]), (1, 30))
        self.c.put(f"/api/posts/{pid}/vote", json={"a_ratio": 50}, headers=lee)   # 바꾸기
        self.assertEqual(self.c.get(f"/api/posts/{pid}", headers=lee).json()["votes"]["a_avg"], 50)
        self.assertEqual(self.c.put(f"/api/posts/{pid}/vote", json={"a_ratio": 10}, headers=self.h).json()["error"],
                         "own_post")

        # 신고 3번이면 숨김 (글쓴이는 계속 봄)
        for name in ("lee", "park", "choi"):
            self.c.post(f"/api/posts/{pid}/report", json={"reason": "광고"}, headers=self.login(name))
        self.assertEqual(self.c.get("/api/posts", headers=lee).json(), [])
        self.assertEqual(self.c.get(f"/api/posts/{pid}", headers=lee).status_code, 404)
        self.assertEqual(self.c.get(f"/api/posts/{pid}", headers=self.h).status_code, 200)

        # 사건을 지우면 글도 지워짐
        self.c.delete(f"/api/cases/{cid}", headers=self.h)
        self.assertEqual(self.c.get("/api/me/posts", headers=self.h).json(), [])

    def test_delete_me(self):
        cid = self.upload()["id"]
        self.assertEqual(self.c.delete("/api/me", headers=self.h).status_code, 204)
        self.assertIsNone(db.get_case(cid))
        self.assertFalse(os.path.exists(db.case_dir(cid)))
        self.assertEqual(self.c.get("/api/me", headers=self.h).json()["error"], "token_invalid")


if __name__ == "__main__":
    unittest.main()
