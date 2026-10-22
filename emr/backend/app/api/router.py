# =============================================================================
# 파일   : app/api/router.py
# 역할   : v1 라우터 집계 — 도메인 라우터를 prefix·tag와 함께 묶음
# 작성일 : 2026-10-13
# 구성   :
#   - api_router  
# =============================================================================
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import auth, bedside_access, bedside_devices, deliveries, delivery_events, locations, maps, notifications, nurses, robot_access, robots, supplies

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
