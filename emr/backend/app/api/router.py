# =============================================================================
# 파일   : app/api/router.py
# 역할   : v1·v2 라우터 집계 — 도메인 라우터를 prefix·tag와 함께 묶음
# 작성일 : 2026-10-13
# 구성   :
#   - api_router     /api/v1
#   - api_v2_router  /api/v2 — 고도화 중인 기능 (2026-10-26 사용자 결정: 음성을 v2로 옮겨 고도화, v1 음성 주소는 없앰)
# =============================================================================
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import auth, bedside_access, bedside_devices, deliveries, delivery_events, fms_inbound, locations, maps, notifications, nurses, omx, robot_access, robots, supplies
from app.api.v2 import voice

api_router = APIRouter()  # main.py가 /api/v1 prefix로 include
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(supplies.router, prefix="/supplies", tags=["supplies"])
api_router.include_router(nurses.router, prefix="/nurses", tags=["nurses"])
api_router.include_router(maps.router, prefix="/maps", tags=["maps"])
api_router.include_router(locations.router, prefix="/locations", tags=["locations"])
api_router.include_router(deliveries.router, prefix="/deliveries", tags=["deliveries"])
api_router.include_router(delivery_events.router, prefix="/delivery-events", tags=["delivery-events"])
api_router.include_router(robots.router, prefix="/robots", tags=["robots"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(robot_access.router, prefix="/robot", tags=["robot-access"])  # 로봇 키 인증
api_router.include_router(bedside_devices.router, prefix="/bedside-devices", tags=["bedside-devices"])  # 관리자 (2026-10-22)
api_router.include_router(bedside_access.router, prefix="/bedside", tags=["bedside-access"])  # 병상 단말 키 인증
api_router.include_router(omx.router, prefix="/omx", tags=["omx"])  # 관리자 — 팀원 OMX 로봇팔 명령·상태 (2026-10-26)
api_router.include_router(fms_inbound.router, prefix="/fms", tags=["fms"])  # 팀원 FMS → EMR 웹훅, 인증 없음 (2026-10-27)

api_v2_router = APIRouter()  # main.py가 /api/v2 prefix로 include
api_v2_router.include_router(voice.router, prefix="/voice", tags=["voice-v2"])  # 간호사 — 음성 배송 예약 초안·안내 음성 (2026-10-26)
