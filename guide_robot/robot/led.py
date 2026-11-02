"""Pinky LED 스트립 (WS281x 8개, pinkylib.LED): 초록 = 앞에 사람, 빨강 = 앞에 다른 것,
노랑 = 검은 바닥 선 (막힌 방), 무지개 = 사람을 찾아 복도를 돌아다니는 중
(색이 스트립을 따라 돌며 밝아졌다 어두워짐, 사람들의 눈길을 끌기 위해).

  python3 robot/led.py green      # 테스트: 초록 3 s
  python3 robot/led.py red
  python3 robot/led.py rainbow    # 10 s
  python3 robot/led.py off
"""
from __future__ import annotations

import colorsys
import math
import sys
import threading
import time

COLORS = {"green": (0, 255, 0), "red": (255, 0, 0), "yellow": (255, 160, 0), "off": (0, 0, 0)}


class Leds:
    def __init__(self, brightness: int = 80, log=print):
        self.log = log
        self.led = None
        self.color = None
        self.lock = threading.Lock()
        self.anim = None
        try:
            from pinkylib import LED
            self.led = LED(brightness=brightness)
        except Exception as e:  # LED 없음 / 권한 없음: 안내원 모드는 LED 없이 계속 동작
            log(f"LED not working ({e}). If pinky_led led_server is running, stop it")

    def set(self, name: str):
        if self.led is None or name == self.color:
            return
        self.color = name
        if name == "rainbow":
            if self.anim is None or not self.anim.is_alive():
                self.anim = threading.Thread(target=self._rainbow, daemon=True)
                self.anim.start()
            return
        with self.lock:
            try:
                rgb = COLORS[name]
                for i in range(self.led.count):
                    self.led.set_pixel(i, rgb)
                self.led.show()
            except Exception as e:
                self.log(f"LED error: {e}")

    def _rainbow(self, hz: float = 15.0, spin: float = 4.0, breath: float = 3.0):
        """스트립을 따라 도는 무지개 (`spin` s에 한 바퀴), `breath` s마다 밝아졌다 어두워짐."""
        t0 = time.monotonic()
        while self.color == "rainbow" and self.led is not None:
            t = time.monotonic() - t0
            level = 0.15 + 0.85 * (0.5 - 0.5 * math.cos(2 * math.pi * t / breath))
            with self.lock:
                if self.color != "rainbow":
                    break
                try:
                    n = self.led.count
                    for i in range(n):
                        r, g, b = colorsys.hsv_to_rgb((i / n + t / spin) % 1.0, 1.0, level)
                        self.led.set_pixel(i, (int(r * 255), int(g * 255), int(b * 255)))
                    self.led.show()
                except Exception as e:
                    self.log(f"LED error: {e}")
                    break
            time.sleep(1.0 / hz)

    def close(self):
        self.color = "off"
        if self.led is not None:
            with self.lock:  # 무지개 스레드의 마지막 프레임 뒤
                try:
                    self.led.clear()
                except Exception:
                    pass


if __name__ == "__main__":
    leds = Leds()
    name = sys.argv[1] if len(sys.argv) > 1 else "green"
    leds.set(name)
    time.sleep(10 if name == "rainbow" else 3)
    leds.close()
