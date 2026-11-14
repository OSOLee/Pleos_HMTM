r"""결과 고정 시험의 기준 응답 다시 저장 (결과를 일부러 바꿨을 때만)

  cd backend
  .venv\Scripts\python tests\golden\save.py            # 전부
  .venv\Scripts\python tests\golden\save.py 이름 ...   # 몇 사건만 (이름은 --list)

저장 전후로 다른 칸을 보여 준다. 저장한 뒤 git diff로 바뀐 결과가 의도한 것인지 확인하고 커밋한다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cases   # noqa: E402


def main(argv):
    if "--list" in argv:
        print("\n".join(cases.names()))
        return 0
    only = [a for a in argv if not a.startswith("-")]
    unknown = sorted(set(only) - set(cases.names()))
    if unknown:
        print(f"[오류] 모르는 사건: {', '.join(unknown)} (목록: --list)")
        return 2
    got = cases.build_all(only or None)
    for name, steps in got.items():
        try:
            d = cases.diff(cases.load(name), steps)
        except FileNotFoundError:
            d = None
        cases.save(name, steps)
        print(f"저장 {name}: " + ("새 파일" if d is None else "같음" if not d else f"{len(d)}칸 바뀜"))
        for line in d or []:
            print("    " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
