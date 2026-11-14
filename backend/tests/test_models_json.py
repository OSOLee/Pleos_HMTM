"""backend/models.json (가중치 목록) 모양 시험. 가중치 파일 자체는 git에 없으므로, 로컬에 파일이 있을 때만 sha256·크기를 대조한다."""
import hashlib
import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "models.json")
ROLES = ("detector", "kind", "scene", "crosswalk")
KEYS = ("file", "role", "version", "sha256", "size_bytes", "source", "classes", "imgsz", "conf")


def load():
    with open(PATH, encoding="utf-8") as fp:
        return json.load(fp)


class ModelsJson(unittest.TestCase):
    def test_shape(self):
        d = load()
        self.assertEqual(d["schema"], "hmtm-models-1")
        self.assertEqual(tuple(d["models"]), ROLES)
        for role, m in d["models"].items():
            for k in KEYS:
                self.assertIn(k, m, f"{role}.{k}")
            self.assertTrue(m["file"].endswith(".pt"), role)

    def test_filled_entries_are_consistent(self):
        """sha256을 채운 항목은 64자리 16진수, 크기도 함께 있어야 한다. 아직 전달 안 된 항목은 둘 다 null"""
        for role, m in load()["models"].items():
            if m["sha256"] is None:
                self.assertIsNone(m["size_bytes"], role)
                continue
            self.assertRegex(m["sha256"], r"^[0-9a-f]{64}$", role)
            self.assertIsInstance(m["size_bytes"], int, role)

    def test_local_files_match_when_present(self):
        """models/ 폴더에 파일이 있으면 목록의 sha256·크기와 같아야 한다 (없으면 건너뜀)"""
        checked = 0
        for role, m in load()["models"].items():
            p = os.path.join(ROOT, "models", m["file"])
            if m["sha256"] is None or not os.path.exists(p):
                continue
            with open(p, "rb") as fp:
                h = hashlib.sha256(fp.read()).hexdigest()
            self.assertEqual((h, os.path.getsize(p)), (m["sha256"], m["size_bytes"]), role)
            checked += 1
        if not checked:
            self.skipTest("로컬에 가중치 파일이 없어 대조하지 않음")


if __name__ == "__main__":
    unittest.main()
