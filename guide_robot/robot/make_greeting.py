"""Pinky의 인사 (Task 01)를 WAV 파일로 한 번 녹음해 두어, Pi는 재생만 하면 되게 함.

  python3 robot/make_greeting.py                 # Google TTS (인터넷 + ffmpeg 필요), 자연스러운 음성
  python3 robot/make_greeting.py --engine espeak # 오프라인, 기계 음성 (sudo apt install espeak-ng)
  aplay sounds/greeting_ko.wav                   # 듣기

노트북에서 하는 것이 가장 쉬움 (pip install gTTS; sudo apt install ffmpeg), 그다음 sounds/greeting_ko.wav를 Pinky로 복사.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
TEXT = "안녕하세요, 인공지능 핑키 안내원입니다. 무엇을 도와 드릴까요?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["gtts", "espeak"], default="gtts")
    ap.add_argument("--text", default=TEXT)
    ap.add_argument("--out", default=os.path.join(ROOT, "sounds", "greeting_ko.wav"))
    a = ap.parse_args()
    os.makedirs(os.path.dirname(a.out), exist_ok=True)

    if a.engine == "espeak":
        if not shutil.which("espeak-ng"):
            raise SystemExit("espeak-ng not found: sudo apt install espeak-ng")
        subprocess.run(["espeak-ng", "-v", "ko", "-s", "150", "-w", a.out, a.text], check=True)
    else:
        try:
            from gtts import gTTS
        except ImportError:
            raise SystemExit("gTTS not found: pip install gTTS   (or --engine espeak)")
        if not shutil.which("ffmpeg"):
            raise SystemExit("ffmpeg not found: sudo apt install ffmpeg   (aplay cannot play mp3)")
        with tempfile.TemporaryDirectory() as d:
            mp3 = os.path.join(d, "g.mp3")
            gTTS(a.text, lang="ko").save(mp3)
            # 모노 22 kHz 16비트: 어떤 USB/3.5 mm 스피커에서도 일반 aplay로 재생됨
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", mp3, "-ac", "1", "-ar", "22050",
                            "-sample_fmt", "s16", a.out], check=True)
    print("->", a.out, f"({os.path.getsize(a.out) // 1024} KB)")


if __name__ == "__main__":
    main()
