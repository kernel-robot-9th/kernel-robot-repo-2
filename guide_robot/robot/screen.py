"""Pinky LCD: Pinky가 말하는 내용 (한국어, 줄바꿈)과 그 사이의 대기 문구를 보여 줌.

  python3 robot/screen.py --probe            # 이 Pinky의 LCD 구동 방식을 찾음
  python3 robot/screen.py "안녕하세요"        # 글자를 그림, ~/guide_screen.png에도 저장

백엔드, 먼저 동작하는 것 사용:
  pinky_lcd Pinky LCD 라이브러리 (~/pinkylib/lcd): LCD().img_show(PIL 영상 320x240), ~/pinky_lcd/lcd_test.py와 같은 방식
  file      ~/guide_screen.png만 저장 (LCD에는 표시 안 함), LCD가 없어도 안내원 모드가 멈추지 않게 함
한국어에는 한글 글꼴이 필요: sudo apt install fonts-nanum
"""
from __future__ import annotations

import glob
import inspect
import os
import sys
import threading

from PIL import Image, ImageChops, ImageDraw, ImageFont

FONT_GLOBS = [
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic*.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-*.ttc",
    "/usr/share/fonts/truetype/unfonts-core/*.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/**/*[Hh]angul*.tt[fc]",
]


def find_font() -> str | None:
    for g in FONT_GLOBS:
        hits = sorted(glob.glob(g, recursive=True))
        if hits:
            return hits[0]
    return None


EMOTION_DIR = "~/pinky_pro/install/pinky_emotion/share/pinky_emotion/emotion"  # angry basic bored fun happy hello interest sad .gif
FACE_ROOTS = [EMOTION_DIR, "~/pinky_lcd", "~/pinkylib", "~/pinky_pro", "~/pinky_ws", "~/ros2_ws", "~/colcon_ws",
              "/opt/ros/*/share/pinky_emotion", "~/*/install/pinky_emotion", "~/*/src/pinky_emotion",
              "~/*/src/*/pinky_emotion"]
FACE_NAMES = ["happy", "smile", "hello", "joy", "basic", "love"]  # 먼저 찾은 이름이 우선


def find_face(name: str = "happy") -> str | None:
    """Pinky 자체 감정 이미지 (pinky_emotion / pinky_lcd 예제): `name`이 있으면 그것, 없으면 happy."""
    exact = os.path.join(os.path.expanduser(EMOTION_DIR), f"{name}.gif")
    if os.path.exists(exact):
        return exact
    files = []
    for root in FACE_ROOTS:
        for r in glob.glob(os.path.expanduser(root)):
            for ext in ("png", "jpg", "jpeg", "gif", "bmp"):
                files += glob.glob(os.path.join(r, "**", f"*.{ext}"), recursive=True)
    for n in [name] + FACE_NAMES:
        hits = sorted(f for f in files if n in os.path.basename(f).lower())
        if hits:
            return hits[0]
    return None


def load_face(path: str | None, box: tuple[int, int]) -> Image.Image | None:
    """첫 프레임을 얼굴 부분만 잘라서 (Pinky GIF는 배경이 많은 전체 화면) box (w, h)를 채우도록
    확대 또는 축소."""
    if not path:
        return None
    try:
        im = Image.open(path)
        im.seek(0)  # GIF: 첫 프레임
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, im.getpixel((0, 0)))
        bbox = ImageChops.difference(im, bg).convert("L").point(lambda v: 255 if v > 24 else 0).getbbox()
        if bbox:
            m = 4
            im = im.crop((max(0, bbox[0] - m), max(0, bbox[1] - m), min(im.width, bbox[2] + m), min(im.height, bbox[3] + m)))
        k = min(box[0] / im.width, box[1] / im.height)
        return im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)
    except Exception:
        return None


def smiley(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float):
    """직접 그린 웃는 얼굴 (LCD 글꼴에는 이모지가 없음)."""
    lw = max(2, int(r / 10))
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 214, 0), outline=(120, 60, 0), width=lw)
    er = r * 0.13
    for ex in (cx - r * 0.35, cx + r * 0.35):
        d.ellipse((ex - er, cy - r * 0.3 - er * 1.4, ex + er, cy - r * 0.3 + er * 1.4), fill=(70, 35, 0))
    d.arc((cx - r * 0.6, cy - r * 0.45, cx + r * 0.6, cy + r * 0.6), 20, 160, fill=(70, 35, 0), width=lw + 1)
    for bx in (cx - r * 0.62, cx + r * 0.62):  # 분홍 볼
        d.ellipse((bx - r * 0.14, cy + r * 0.08, bx + r * 0.14, cy + r * 0.24), fill=(255, 140, 150))


def render(text: str, size=(320, 240), fg=(255, 255, 255), bg=(255, 105, 180), font_path=None,
           face: bool = True, face_img: Image.Image | None = None) -> Image.Image:
    """분홍 화면 가운데의 글자, 글자 단위로 줄바꿈 (한국어에는 긴 단어가 없음),
    위에 웃는 얼굴."""
    w, h = size
    if face and face_img is not None:
        c = face_img.getpixel((0, 0))
        if c[3] > 200:  # Pinky 이모지는 자체 배경색이 있음: 화면 전체에 그 색을 쓰고 주위에 테두리 없음
            bg = c[:3]
            fg = (0, 0, 0) if sum(bg) > 3 * 150 else (255, 255, 255)
    img = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(img)
    top = 0
    if face:
        if face_img is not None:  # Pinky 자체 이모지, 크게: 화면 위쪽 ~60%
            img.paste(face_img, (int(w / 2 - face_img.width / 2), 6), face_img)
            top = 6 + face_img.height + 6
        else:
            r = h * 0.17
            smiley(d, w / 2, 8 + r, r)
            top = int(16 + 2 * r)
        h -= top
    font_path = font_path or find_font()
    for fs in range(min(40 if face else 56, h // 2), 9, -2):  # 들어가는 가장 큰 글꼴
        font = ImageFont.truetype(font_path, fs) if font_path else ImageFont.load_default()
        lines = wrap(text, font, d, w - 16)
        lh = fs + fs // 3
        if lh * len(lines) <= h - 16 or not font_path:
            break
    y = top + (h - lh * len(lines)) // 2
    for ln in lines:
        lw = d.textlength(ln, font=font)
        d.text(((w - lw) / 2, y), ln, font=font, fill=fg)
        y += lh
    return img


def wrap(text: str, font, d: ImageDraw.ImageDraw, maxw: int) -> list[str]:
    lines = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split(" "):
            t = (cur + " " + word).strip()
            if d.textlength(t, font=font) <= maxw:
                cur = t
                continue
            if cur:
                lines.append(cur)
            cur = ""
            for ch in word:  # 줄보다 긴 단어: 글자 사이에서 줄바꿈
                if d.textlength(cur + ch, font=font) > maxw and cur:
                    lines.append(cur)
                    cur = ""
                cur += ch
        lines.append(cur)
    return lines


class Screen:
    def __init__(self, size=(320, 240), rotate: int = 0, log=print, face: str = ""):
        self.size, self.rotate, self.log = size, rotate, log
        box = (size[0] - 20, int(size[1] * 0.58))
        self.face_path = os.path.expanduser(face) if face else find_face("happy")
        self.face = load_face(self.face_path, box)
        hello = None if face else find_face("hello")
        self.faces = {"happy": self.face, "hello": load_face(hello, box) or self.face}
        log(f"face: {self.face_path}" + (f", greeting: {hello}" if hello else "") if self.face is not None else
            "face: Pinky's emoji images not found, drawing a smiley (set the path with face_image:=...)")
        self.show_fn = None
        self.backend = "file"
        self.lock = threading.Lock()
        if not find_font():
            log("no Korean font: sudo apt install fonts-nanum (otherwise letters show as boxes)")
        self.lcd = None
        try:
            from pinky_lcd import LCD
            self.lcd = LCD()
            self.show_fn, self.backend = self.lcd.img_show, "pinky_lcd.LCD.img_show"
        except Exception as e:  # LCD 라이브러리 없음: 계속 진행, 파일로만 저장
            log(f"LCD not found ({e}); writing to ~/guide_screen.png only")

    def close(self):
        with self.lock:
            if self.lcd is not None and hasattr(self.lcd, "close"):
                self.lcd.close()
                self.lcd = self.show_fn = None

    def text(self, text: str, face: str = "happy"):
        """백그라운드 스레드에서 그림: SPI LCD는 프레임당 ~0.1 s 걸릴 수 있음. face: happy, hello, 또는 None (글자만)."""
        threading.Thread(target=self._draw, args=(text, face), daemon=True).start()

    def _draw(self, text: str, face: str = "happy"):
        img = render(text, self.size, face=face is not None, face_img=self.faces.get(face, self.face))
        if self.rotate:
            img = img.rotate(self.rotate, expand=True)
        with self.lock:
            try:
                img.save(os.path.expanduser("~/guide_screen.png"))
                if self.show_fn is not None:
                    self.show_fn(img)
            except Exception as e:
                self.log(f"LCD error: {e}")


def probe():
    print("~/pinky_lcd:", sorted(os.listdir(os.path.expanduser("~/pinky_lcd"))) if os.path.isdir(os.path.expanduser("~/pinky_lcd")) else "missing")
    print("~/pinkylib:", sorted(os.listdir(os.path.expanduser("~/pinkylib"))) if os.path.isdir(os.path.expanduser("~/pinkylib")) else "missing")
    print("font:", find_font())
    print("face:", find_face())
    sys.path.insert(0, os.path.expanduser("~/pinkylib"))
    try:
        import pinkylib
        print("pinkylib:", getattr(pinkylib, "__file__", "?"))
        print("  names:", [n for n in dir(pinkylib) if not n.startswith("_")])
        cls = getattr(pinkylib, "LCD", None)
        if cls:
            print("  LCD", inspect.signature(cls))
            for n, f in inspect.getmembers(cls, callable):
                if not n.startswith("_"):
                    try:
                        print(f"    .{n}{inspect.signature(f)}")
                    except (TypeError, ValueError):
                        print(f"    .{n}")
    except Exception as e:
        print("pinkylib import:", repr(e))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--probe":
        probe()
    else:
        s = Screen()
        print("backend:", s.backend)
        s._draw(sys.argv[1] if len(sys.argv) > 1 else "안녕하세요, 인공지능 핑키 안내원입니다. 무엇을 도와 드릴까요?")
        print("-> ~/guide_screen.png")
        import time
        time.sleep(5)  # LCD를 확인하세요
        s.close()
