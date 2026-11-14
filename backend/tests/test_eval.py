"""평가 숫자가 떨어지지 않았는지 (회귀 시험)

  MTM_SLOW=1 python -m unittest tests.test_eval -v     # 평가 24개를 임시 폴더에서 다시 돌림 (10분 안팎)

outputs/eval_auto, outputs/eval_tap을 임시 폴더에 복사해서 지금 코드로 다시 돌리고(탐지는 저장된 tracks.json 재사용),
결과표의 숫자가 기준 이상인지 본다. outputs는 건드리지 않음. 숫자가 좋아지면 BASELINE을 올려 둘 것.
재학습 모델로 바꿀 때는 tracks.json을 지우고 탐지부터 다시 돌려야 해서 이 시험만으로는 부족함.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLOW = os.environ.get("MTM_SLOW") == "1"
# 2026-10-27 기준 (결과표_자동.md, 결과표_답반영.md). 선진입 답 매핑을 고쳐 180629가 맞아서 7 → 8
BASELINE = {"auto": {"party": 10, "ratio": 1}, "tap": {"party": 24, "ratio": 8}}


def rerun(src, dst, with_answers):
    shutil.copytree(src, dst)
    for name in sorted(os.listdir(dst)):
        d = os.path.join(dst, name)
        args = [sys.executable, "run_app.py", f"data/videos/cc/{name}.mp4", "--out", d]
        if with_answers:
            args += ["--answers", os.path.join(d, "answers.json")]
        p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=600)
        assert "Traceback" not in p.stdout + p.stderr, f"{name}: {(p.stdout + p.stderr)[-1000:]}"


def score(folder):
    p = subprocess.run([sys.executable, "tools/evaluate/results_table.py", folder], cwd=ROOT, capture_output=True, text=True)
    m = re.search(r"당사자 일치 (\d+)/(\d+), 비율 일치 (\d+)/", p.stdout)
    assert m, p.stdout[-500:] + p.stderr[-500:]
    return {"party": int(m.group(1)), "n": int(m.group(2)), "ratio": int(m.group(3))}


@unittest.skipUnless(SLOW and os.path.isdir(os.path.join(ROOT, "outputs/eval_tap")), "MTM_SLOW=1일 때만 (느림)")
class Evaluation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="mtm_eval_")
        cls.scores = {}
        for kind, folder, with_answers in (("auto", "eval_auto", False), ("tap", "eval_tap", True)):
            dst = os.path.join(cls.tmp, kind)
            rerun(os.path.join(ROOT, "outputs", folder), dst, with_answers)
            cls.scores[kind] = score(dst)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_not_worse(self):
        for kind, base in BASELINE.items():
            s = self.scores[kind]
            print(f"\n{kind}: 당사자 {s['party']}/{s['n']}, 비율 {s['ratio']}/{s['n']} (기준 {base})")
            with self.subTest(kind):
                self.assertGreaterEqual(s["party"], base["party"])
                self.assertGreaterEqual(s["ratio"], base["ratio"])


if __name__ == "__main__":
    unittest.main()
