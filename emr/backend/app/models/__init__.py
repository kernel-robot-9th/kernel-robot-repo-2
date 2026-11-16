# =============================================================================
# 파일   : app/models/__init__.py
# 역할   : ORM 모델 패키지 진입점 — Alembic autogenerate용 전체 import
# 작성일 : 2026-10-13
# 구성   :
#   - Base + 12 모델  nurses, supplies, maps, locations, deliveries, delivery_items, robots,
#                    delivery_events (배송 기록 — 2026-10-21), bedside_devices (병상 단말 — 2026-10-22),
#                    robot_status_reports (로봇 배터리·오염도 마지막 보고 — 2026-10-23),
#                    fms_orders (팀원 FMS에 보낸 물품 1개 주문 — 2026-10-27), fms_batches (FMS 묶음의 OMX 적재 진행 — 2026-10-27)
# =============================================================================
"""Alembic autogenerate가 전 모델을 보도록 여기서 전부 import한다."""
from app.models.base import Base
from app.models.bedside_device import BedsideDevice
from app.models.delivery import Delivery, DeliveryItem
from app.models.delivery_event import DeliveryEvent
from app.models.fms_batch import FmsBatch
from app.models.fms_order import FmsOrder
from app.models.location import Location
from app.models.map import Map
from app.models.nurse import Nurse
from app.models.robot import Robot
from app.models.robot_status_report import RobotStatusReport
from app.models.supply import Supply

__all__ = ["Base", "BedsideDevice", "Delivery", "DeliveryEvent", "DeliveryItem", "FmsBatch", "FmsOrder", "Location", "Map", "Nurse", "Robot", "RobotStatusReport", "Supply"]
