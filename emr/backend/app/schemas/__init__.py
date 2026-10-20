# =============================================================================
# 파일   : app/schemas/__init__.py
# 역할   : Pydantic I/O 스키마 패키지
# 작성일 : 2026-10-13
# 구성   :
#   - *Create/*Update  입력
#   - *Out             출력 (OrmOut 상속)
# =============================================================================
from app.schemas.auth import LoginIn, TokenOut
from app.schemas.delivery import (
    DeliveryCreate, DeliveryItemIn, DeliveryItemOut,
    DeliveryOut, DeliveryUpdate,
)
from app.schemas.location import LocationCreate, LocationOut, LocationUpdate
from app.schemas.map import MapCreate, MapOut, MapUpdate
from app.schemas.nurse import NurseCreate, NurseOut, NurseUpdate
from app.schemas.robot import RobotCreate, RobotOut, RobotUpdate
from app.schemas.supply import SupplyCreate, SupplyOut, SupplyUpdate

__all__ = [n for n in dir() if n[0].isupper()]
