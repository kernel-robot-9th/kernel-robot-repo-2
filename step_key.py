"""Wait for SPACE in the terminal before each motion step (--step in eval_bi_api_yolo.py).

SPACE = do this step, q = stop here (torque stays on). Without a terminal it falls back to Enter.
"""
import sys
import termios
import tty


class StepCancelled(RuntimeError):
    pass


def wait_space(step):
    print(f"[STEP] next: {step}  (SPACE = go, q = stop)", flush=True)
    stream = sys.stdin
    if not stream.isatty():
        if stream.readline().strip().lower() == "q":
            raise StepCancelled(f"stopped before {step} (취소)")
        return
    fd = stream.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        termios.tcflush(fd, termios.TCIFLUSH)  # ignore keys pressed while the arm was moving
        while True:
            key = stream.read(1)
            if key == " ":
                return
            if key.lower() == "q":
                raise StepCancelled(f"stopped before {step} (취소)")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
