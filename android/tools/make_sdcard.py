r"""에뮬레이터용 가상 SD 카드(FAT32 이미지) 만들기 — 블랙박스 메모리 카드 흉내 (docs/design-blackbox.md 7.1)

  py -3.12 -m venv %TEMP%\fatvenv
  %TEMP%\fatvenv\Scripts\python -m pip install pyfatfs "setuptools<81"   # fs 패키지가 pkg_resources를 씀
  %TEMP%\fatvenv\Scripts\python android\tools\make_sdcard.py blackbox.img 20261109_143012_F.mp4 [영상 ...]

영상은 카드 안 Normal/Front/<파일 이름>으로 들어간다 (블랙박스 폴더 모양).
에뮬레이터: emulator -avd Pleos_Connect_v2.1.0 -read-only -sdcard blackbox.img
이미지를 바꾸려면 에뮬레이터를 끄고 다시 만든다 (켜진 동안 파일이 잠김).
"""
import argparse
import os
import sys

from pyfatfs.PyFat import PyFat
from pyfatfs.PyFatFS import PyFatFS


def main():
    p = argparse.ArgumentParser(description="블랙박스 SD 카드 이미지(FAT32) 만들기")
    p.add_argument("image", help="만들 이미지 파일 (.img)")
    p.add_argument("videos", nargs="+", help="넣을 영상 파일")
    p.add_argument("--size-mb", type=int, default=128, help="이미지 크기 MB (FAT32는 33MB 이상, 기본 128)")
    p.add_argument("--label", default="BLACKBOX", help="볼륨 이름 (최대 11자)")
    p.add_argument("--dir", default="Normal/Front", help="카드 안 폴더 (기본 Normal/Front)")
    a = p.parse_args()

    need = sum(os.path.getsize(v) for v in a.videos)
    if need > (a.size_mb - 8) << 20:
        sys.exit(f"영상 합계 {need >> 20}MB가 이미지에 안 들어가요. --size-mb를 늘려 주세요")
    with open(a.image, "wb") as f:
        f.truncate(a.size_mb << 20)
    fat = PyFat()
    fat.mkfs(a.image, PyFat.FAT_TYPE_FAT32, size=a.size_mb << 20, label=a.label[:11].upper())
    fat.close()

    fs = PyFatFS(a.image)
    try:
        fs.makedirs("/" + a.dir.strip("/"), recreate=True)
        for v in a.videos:
            dst = f"/{a.dir.strip('/')}/{os.path.basename(v)}"
            with open(v, "rb") as src, fs.openbin(dst, "w") as out:
                while chunk := src.read(1 << 20):
                    out.write(chunk)
            print(f"넣음: {dst} ({os.path.getsize(v):,} 바이트)")
    finally:
        fs.close()
    print(f"완료: {a.image} ({a.size_mb}MB, {a.label})")


if __name__ == "__main__":
    main()
