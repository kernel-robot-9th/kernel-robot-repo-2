# =============================================================================
# 파일   : app/models/map.py
# 역할   : maps — 로봇 맵 파일과 맵 정보 (ROS map_server yaml 기준)
# 작성일 : 2026-10-14
# 구성   :
#   - Map  맵 정보 + 업로드한 맵 이미지(PNG로 변환해 DB에 저장, 2026-10-19)
# =============================================================================
from __future__ import annotations

from sqlalchemy import CheckConstraint, Float, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.models.base import Base, TimestampMixin

# 이미지·크기·원래 파일 이름은 함께 있거나 함께 없다
IMAGE_ALL_OR_NONE_SQL = (
    "(image_png IS NULL AND image_width_px IS NULL AND image_height_px IS NULL AND image_file_name IS NULL)"
    " OR (image_png IS NOT NULL AND image_width_px > 0 AND image_height_px > 0 AND image_file_name IS NOT NULL)"
)


class Map(TimestampMixin, Base):
    """로봇 맵 한 장. 장소(locations)의 좌표는 이 맵 기준이다.
    로봇(Pinky, slam_toolbox)이 쓰는 map_server yaml + 이미지를 올리면 숫자를 읽어 넣고 이미지를 PNG로 보관한다(화면 표시용).
    로봇이 실제로 쓰는 맵 파일은 로봇 쪽이 따로 관리한다. 숫자만 넣고 이미지가 없는 맵도 있다.
    """

    __tablename__ = "maps"
    __table_args__ = (
        CheckConstraint("resolution_m_per_pixel > 0", name="ck_maps_resolution_m_per_pixel"),
        CheckConstraint(IMAGE_ALL_OR_NONE_SQL, name="ck_maps_image_all_or_none"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)  # 사람이 부르는 이름 (예: "3병동")
    file_name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)  # 맵 yaml 파일 이름 (예: "ward3.yaml")
    # 맵 정보는 ROS map_server yaml(resolution, origin) 형식 — Pinky Pro(slam_toolbox·Nav2)가 쓰는 형식과 같다 (2026-10-19 확인)
    resolution_m_per_pixel: Mapped[float] = mapped_column(Float, nullable=False)  # 픽셀 하나의 크기, 미터
    origin_x_m: Mapped[float] = mapped_column(Float, nullable=False)      # 맵 이미지 왼쪽 아래 픽셀의 x, 미터
    origin_y_m: Mapped[float] = mapped_column(Float, nullable=False)      # 맵 이미지 왼쪽 아래 픽셀의 y, 미터
    origin_yaw_rad: Mapped[float] = mapped_column(Float, nullable=False)  # 맵 회전, 라디안
    # 업로드한 맵 이미지 (PGM·PNG → PNG, 흑백 맵은 흑백·색 평면도는 색). 목록 조회 때 읽지 않도록 deferred — GET /maps/{id}/image에서만 읽는다
    image_png: Mapped[bytes | None] = deferred(mapped_column(LargeBinary))
    image_width_px: Mapped[int | None] = mapped_column(Integer)   # 이미지 가로 픽셀
    image_height_px: Mapped[int | None] = mapped_column(Integer)  # 이미지 세로 픽셀 (좌표 변환에 필요: ROS는 y가 위로)
    image_file_name: Mapped[str | None] = mapped_column(String(128))  # 올린 이미지의 원래 이름 (예: my_map.pgm)

    @property
    def has_image(self) -> bool:
        """맵 이미지가 있는지 (MapOut용). image_png를 읽지 않고 크기 컬럼으로 판단한다.
        [입력] 없음
        [출력] bool
        """
        return self.image_width_px is not None
