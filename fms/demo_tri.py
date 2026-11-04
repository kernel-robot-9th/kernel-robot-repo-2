"""발표 영상용 3분할 (11-03): ② ③ ④ 만 세로로 긴 칸 3개 — 칸 위에 단계 · 경과 · 완료. 쓰는 법은 demo_quad.py 와 같음.

  python3 demo_tri.py             # 서버 3개 띄움 → 브라우저로 http://localhost:8792/tri.html (F11 전체 화면)
                                  # → 화면 녹화 시작 → 여기서 Enter → 주문 9건이 셋에 동시에 들어가고 시간이 흐름
  python3 demo_tri.py --speed 8 --no-wait

칸 (fms_core.PROFILES): ② v2 처음 CBS · ③ v3 주차 + 직선 · ④ v4 지금. Ctrl+C 로 서버 3개를 모두 끈다.
"""
from demo_quad import main

PANELS = [(8792, 'v2', 3), (8793, 'v3', 3), (8794, 'v4', 3)]   # static/tri.html 과 같은 포트 (4분할과 따로 띄울 수 있게)

if __name__ == '__main__':
    main(PANELS, 'tri.html')
