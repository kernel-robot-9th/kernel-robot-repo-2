# =============================================================================
# 파일   : app/models/location.py
# 역할   : locations — 배송 위치(장소)와 맵 좌표
# 작성일 : 2026-10-14
# 구성   :
#   - Location  
# =============================================================================
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.map import Map


class Location(TimestampMixin, Base):
    """배송 위치(병실·스테이션 등)와 로봇 맵 좌표. 좌표는 map_id가 가리키는 맵 기준이다.
    좌표 세 값은 전부 있거나 전부 없어야 한다(CHECK). 없으면 "좌표 미등록" — 이름만 먼저 등록하고 로봇 부서가 나중에 채운다.
    좌표를 넣을 때는 맵도 지정해야 한다 (서비스에서 검사).
    """

    __tablename__ = "locations"
    __table_args__ = (
        CheckConstraint(
            "(map_x_m IS NULL AND map_y_m IS NULL AND map_yaw_rad IS NULL) OR "
            "(map_x_m IS NOT NULL AND map_y_m IS NOT NULL AND map_yaw_rad IS NOT NULL)",
            name="ck_locations_map_pose_all_or_none",
        ),
        UniqueConstraint("robot_dest", name="uq_locations_robot_dest"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)  # 장소 이름 (예: "301호")
    # [검토 필요] 좌표계·단위는 가정값(맵 원점 기준 미터, 반시계 방향 라디안). 로봇 부서의 맵 프레임과 일치하는지 확인 필요.
    map_x_m: Mapped[float | None] = mapped_column(Float)      # 맵 좌표 x, 미터
    map_y_m: Mapped[float | None] = mapped_column(Float)      # 맵 좌표 y, 미터
    map_yaw_rad: Mapped[float | None] = mapped_column(Float)  # 도착 시 로봇이 바라볼 방향, 라디안
    map_id: Mapped[int | None] = mapped_column(ForeignKey("maps.id", name="fk_locations_map_id"))  # 좌표가 속한 맵
    # 로봇 목적지 이름 — 팀원 Pinky API GET /dests의 이름(예: PHARMACY). 실행기가 POST /goto {"dest"}로 쓴다 (2026-10-22, 0011)
    robot_dest: Mapped[str | None] = mapped_column(String(64))
    # 로봇 전용 장소(충전·출발점·대기 포켓) — 비품 배송 불가, 품목 없는 로봇 이동만(도착 = 완료). 병상 병실 불가. 복귀 장소로는 쓴다 (2026-10-22, 0012)
    robot_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))

    map: Mapped[Map | None] = relationship()
