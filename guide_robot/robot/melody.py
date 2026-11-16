"""Pinky GPIO 부저의 짧은 인사 멜로디 (부저는 말을 할 수 없음), 그리고 Task 01 테스트.

  python3 robot/melody.py          # 멜로디 + LCD에 인사 문장, ROS 불필요
  python3 robot/melody.py --tune   # 멜로디만
"""
from __future__ import annotations

import sys
import time

C6, D6, E6, F6, G6, A6, B6, C7 = 1047, 1175, 1319, 1397, 1568, 1760, 1976, 2093
G5 = 784
# (주파수 Hz, 초); 0 = 쉼표. 다장조의 밝은 ~3.5 s "안녕" 멜로디 (부저는 1-2 kHz에서 가장 잘 울림):
# 올라가는 아르페지오, 짧게 뛰는 응답, 으뜸음으로 천천히 끝남.
GREETING_TUNE = [
    (G5, 0.12), (C6, 0.12), (E6, 0.12), (G6, 0.30),
    (E6, 0.12), (G6, 0.36), (0, 0.10),
    (A6, 0.12), (G6, 0.12), (F6, 0.12), (E6, 0.12), (D6, 0.24), (G6, 0.24), (0, 0.06),
    (E6, 0.14), (D6, 0.14), (B6, 0.14), (C7, 0.55),
]


def play(buzzer, tune=GREETING_TUNE, duty: float = 50, gap: float = 0.025):
    """buzzer = buzzer_start() 후의 pinkylib.Buzzer(). ~3.5 s 동안 블록됨.
    음마다 짧은 쉼 (gap)을 두어 반복음과 이웃 음이 구분되어 들리게 함."""
    for freq, dur in tune:
        if freq:
            buzzer.set_buzzer_freq(freq)
            buzzer.set_buzzer_duty(duty)
            time.sleep(max(0.0, dur - gap))
            buzzer.set_buzzer_duty(0)
            time.sleep(gap)
        else:
            buzzer.set_buzzer_duty(0)
            time.sleep(dur)
    buzzer.set_buzzer_duty(0)


def main():
    from pinkylib import Buzzer
    b = Buzzer()
    b.buzzer_start(1000)
    scr = None
    if "--tune" not in sys.argv:
        from screen import Screen
        scr = Screen()
        print("screen:", scr.backend)
        scr.text("안녕하세요, 인공지능 핑키 안내원입니다. 무엇을 도와 드릴까요?")
    play(b)
    if scr:
        time.sleep(4)
        scr.close()
    b.pwm.stop()


if __name__ == "__main__":
    main()
