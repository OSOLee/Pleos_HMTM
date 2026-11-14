"""블랙박스 사건 저장 시험 (bb_cases 표, docs/design-blackbox.md 3.5)

  python -m pytest tests/test_bb_store.py
"""
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from src.blackbox import store
from src.server import db


class TempBB(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hmtm_bb_")
        self._old = db.CASES_DIR, db.DB_PATH, store.BB_DIR
        db.CASES_DIR, db.DB_PATH = self.tmp, os.path.join(self.tmp, "server.db")
        store.BB_DIR = os.path.join(self.tmp, "bb_cases")

    def tearDown(self):
        db.CASES_DIR, db.DB_PATH, store.BB_DIR = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)


class Store(TempBB):
    def test_table_in_same_db_file(self):
        db.row("SELECT 1")
        with store.connect():
            pass
        con = sqlite3.connect(db.DB_PATH)
        names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        cols = {r[1] for r in con.execute("PRAGMA table_info(bb_cases)")}
        con.close()
        self.assertTrue({"users", "cases", "bb_cases"} <= names)
        self.assertTrue({"analyzer_name", "analyzer_version", "bb_facts", "sync", "video_kept"} <= cols)

    def test_lifecycle(self):
        cid = store.create("u1", {"filename": "a.mp4"}, None, scenario="rear_end_lead")
        self.assertTrue(os.path.isdir(store.case_dir(cid)))
        row = store.get(cid)
        self.assertEqual((row["status"], row["owner"], row["scenario"], row["vehicle"]), ("analyzing", "u1", "rear_end_lead", None))
        self.assertEqual(row["view"]["status"], "analyzing")
        self.assertEqual(store.analyzing_ids(), [cid])
        store.set_progress(cid, 40)
        self.assertEqual(store.get(cid)["view"]["progress"], 40)

        bb = {"analyzer": {"name": "fake", "version": "0.1.0"}, "status": "ok"}
        rec = {"rule_results": [{"rule": "movement_v0"}], "rules": ["movement_v0"], "judge_version": "0.13.1"}
        view = store.finish(cid, "done", bb, {"grade": "none"}, {"answers": {}}, rec, video_kept=False)
        self.assertEqual((view["status"], view["id"], view["progress"]), ("done", cid, 100))
        row = store.get(cid)
        self.assertEqual((row["analyzer_name"], row["analyzer_version"]), ("fake", "0.1.0"))
        self.assertEqual((row["rules"], row["judge_version"], row["video_kept"]), (["movement_v0"], "0.13.1", False))
        self.assertEqual(row["view"], view)
        self.assertEqual(store.analyzing_ids(), [])
        store.set_progress(cid, 10)                       # 끝난 사건은 진행률이 안 바뀜
        self.assertEqual(store.get(cid)["view"]["progress"], 100)

        store.delete(cid)
        self.assertIsNone(store.get(cid))
        self.assertFalse(os.path.exists(store.case_dir(cid)))

    def test_delete_owner(self):
        a, b = store.create("u1", {}, None), store.create("u1", {}, None)
        c = store.create("u2", {}, {"samples": []})
        self.assertEqual(store.delete_owner("u1"), 2)
        self.assertIsNone(store.get(a))
        self.assertFalse(os.path.exists(store.case_dir(b)))
        self.assertEqual(store.get(c)["vehicle"], {"samples": []})


if __name__ == "__main__":
    unittest.main()
