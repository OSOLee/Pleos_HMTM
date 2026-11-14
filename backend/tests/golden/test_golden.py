"""결과 고정 시험: 지금 서버 응답이 저장한 기준 응답(tests/golden/data/*.json)과 같은지 (README.md)

  python -m pytest tests/golden

가짜 분석기로 데모 사건·차량 사건을 만들고 정해진 답을 보낸 뒤 단계마다 응답을 비교한다.
다르면 다른 칸을 모두 보여 준다. 결과를 일부러 바꿨으면 `python tests/golden/save.py`로 다시 저장한다.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cases   # noqa: E402


class Golden(unittest.TestCase):
    got = None

    @classmethod
    def setUpClass(cls):
        cls.got = cases.build_all()

    def test_same_cases(self):
        """저장한 사건 파일과 정의한 사건이 같음 (지운 사건의 파일이 남거나, 새 사건을 저장 안 함)"""
        files = sorted(os.path.splitext(n)[0] for n in os.listdir(cases.DATA) if n.endswith(".json"))
        self.assertEqual(files, sorted(cases.names()), "tests/golden/save.py로 다시 저장하세요")

    def test_responses(self):
        for name in cases.names():
            with self.subTest(name):
                saved = cases.load(name)
                d = cases.diff(saved, self.got[name])
                if d:
                    self.fail(f"{name}: {len(d)}칸 다름 (일부러 바꿨으면 tests/golden/save.py {name})\n  "
                              + "\n  ".join(d))


if __name__ == "__main__":
    unittest.main()
