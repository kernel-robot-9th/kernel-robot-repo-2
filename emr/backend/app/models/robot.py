# =============================================================================
# 파일   : app/models/robot.py
# 역할   : robots — 로봇 등록·종류·이름·상태
# 작성일 : 2026-10-14
# 구성   :
#   - Robot  api_key_hash·api_key_issued_at: 수령 확인 API용 로봇별 키 (2026-10-19)
#            home_location_id: 배송을 마치거나 실패하면 돌아갈 복귀 장소 (2026-10-20)
#            robot_server_url: 로봇 서버(팀원 Pinky API) 주소 — claim 때 EMR이 /status를 묻는다 (2026-10-23)
#            status_report: 그때 받은 마지막 배터리·오염도 (robot_status_reports, 2026-10-23)
# =============================================================================
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import RobotStatus, RobotType, check_values

if TYPE_CHECKING:
    from app.models.location import Location
    from app.models.robot_status_report import RobotStatusReport


class Robot(TimestampMixin, Base):
    """로봇 기본 정보. 우리 DB가 원본이며, 등록·종류·이름·상태를 관리한다. 배터리·오염도는 claim 때 로봇 서버에서 받은 마지막 값(status_report, 2026-10-23), 위치는 없음.
    종류는 매니퓰레이터(적재)와 AMR(주행) 두 가지.
    """

    __tablename__ = "robots"
    __table_args__ = (
        CheckConstraint(f"status IN ({check_values(RobotStatus)})", name="ck_robots_status"),
        CheckConstraint(f"robot_type IN ({check_values(RobotType)})", name="ck_robots_robot_type"),
        UniqueConstraint("api_key_hash", name="uq_robots_api_key_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)  # 로봇 이름 (예: "배송로봇 1호")
    robot_type: Mapped[str] = mapped_column(String(16), nullable=False)  # manipulator | amr. 등록 후 변경 불가
    status: Mapped[str] = mapped_column(String(16), default=RobotStatus.IDLE, nullable=False)
    # 로봇이 EMR API(수령 확인)를 부를 때 쓰는 키의 sha256. 평문은 발급 응답에서 한 번만 보여 준다. NULL=키 없음
    api_key_hash: Mapped[str | None] = mapped_column(String(64))
    api_key_issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 복귀 장소. 복귀 장소로 쓰는 장소는 지울 수 없다(RESTRICT, 서비스가 409 location_is_robot_home). NULL=미지정
    # 로봇 서버(팀원 Pinky API) 주소, 예: http://192.168.129.107:8080. NULL이면 상태를 물을 수 없어 배송을 맡지 않는다 (2026-10-23)
    robot_server_url: Mapped[str | None] = mapped_column(String(255))
    home_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id", name="fk_robots_home_location_id", ondelete="RESTRICT")
    )

    home_location: Mapped[Location | None] = relationship()
    # claim 때 로봇 서버에서 받은 마지막 상태. 받은 적이 없으면 None (2026-10-23)
    status_report: Mapped[RobotStatusReport | None] = relationship(passive_deletes=True)

    @property
    def has_api_key(self) -> bool:
        """키가 발급되어 있는지 (RobotOut용).
        [입력] 없음
        [출력] bool
        """
        return self.api_key_hash is not None
