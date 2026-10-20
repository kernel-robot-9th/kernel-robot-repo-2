# =============================================================================
# 파일   : scripts/seed.py
# 역할   : 개발용 초기 데이터 (python -m scripts.seed)
# 작성일 : 2026-10-13
# 구성   :
#   - main()  멱등 시드
# =============================================================================
from __future__ import annotations

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import Location, Map, Nurse, Robot, Supply
from app.services.supply import auto_expiry_date
from app.models.enums import NurseRole


def main() -> None:
    """개발용 초기 데이터 삽입. 테이블마다 비어 있을 때만 채운다 (멱등).
    [입력] 없음 (alembic upgrade head 선행)
    [출력] 없음. 간호사 2명(N001 관리자·N002 일반 / nurse1234), 비품 9종, 맵 1장, 장소 4곳, 로봇 2대(AMR·매니퓰레이터)
    """
    with SessionLocal() as db:
        seeded = []
        if not db.query(Nurse).count():
            db.add_all([
                Nurse(employee_no="N001", name="김간호", password_hash=hash_password("nurse1234"), role=NurseRole.ADMIN),
                Nurse(employee_no="N002", name="이간호", password_hash=hash_password("nurse1234"), role=NurseRole.NURSE),
            ])
            seeded.append("nurses N001 admin / N002 nurse (password nurse1234)")
        if not db.query(Supply).count():
            db.add_all([
                Supply(code="MED-A", name="A 약품", category="medication", requestable_by="nurse", stock_qty=100, expiry_date=auto_expiry_date()),
                Supply(code="MED-B", name="B 약품", category="medication", requestable_by="nurse", stock_qty=100, expiry_date=auto_expiry_date()),
                Supply(code="MED-C", name="C 약품", category="medication", requestable_by="nurse", stock_qty=100, expiry_date=auto_expiry_date()),
                Supply(code="INJ-1", name="주사제", category="medication", requestable_by="nurse", stock_qty=50, expiry_date=auto_expiry_date()),
                Supply(code="SUP-BLK", name="이불", category="supply", requestable_by="patient", stock_qty=30, expiry_date=auto_expiry_date()),
                Supply(code="SUP-PAD", name="매트리스 패드", category="supply", requestable_by="patient", stock_qty=30, expiry_date=auto_expiry_date()),
                Supply(code="SUP-GWN", name="환자복", category="supply", requestable_by="patient", stock_qty=40, expiry_date=auto_expiry_date()),
                Supply(code="SUP-SLP", name="실내화", category="supply", requestable_by="patient", stock_qty=40, expiry_date=auto_expiry_date()),
                Supply(code="SUP-CUP", name="플라스틱 컵", category="supply", requestable_by="patient", stock_qty=200, expiry_date=auto_expiry_date()),
            ])
            seeded.append("supplies 9")
        if not db.query(Map).count():
            # 예시값 — 로봇 부서의 실제 맵 yaml 값으로 교체해야 한다
            ward_map = Map(name="3병동", file_name="ward3.yaml", resolution_m_per_pixel=0.05,
                           origin_x_m=-10.0, origin_y_m=-10.0, origin_yaw_rad=0.0)
            db.add(ward_map); db.flush()
            # 맵이 없던 시절에 만든 좌표 있는 장소를 이 맵에 연결
            orphaned = db.query(Location).filter(Location.map_id.is_(None), Location.map_x_m.isnot(None)).all()
            for location in orphaned:
                location.map_id = ward_map.id
            seeded.append(f"maps 1 (linked {len(orphaned)} locations)")
        if not db.query(Location).count():
            ward_map_id = db.query(Map.id).filter(Map.name == "3병동").scalar()
            # 좌표는 예시값 — 실제 맵 좌표로 교체해야 한다
            db.add_all([
                Location(name="비품실", map_x_m=0.0, map_y_m=0.0, map_yaw_rad=0.0, map_id=ward_map_id),
                Location(name="간호사스테이션", map_x_m=8.0, map_y_m=2.0, map_yaw_rad=1.57, map_id=ward_map_id),
                Location(name="301호", map_x_m=12.5, map_y_m=3.2, map_yaw_rad=1.57, map_id=ward_map_id),
                Location(name="302호", map_x_m=16.0, map_y_m=3.2, map_yaw_rad=1.57, map_id=ward_map_id),
            ])
            seeded.append("locations 4")
        if not db.query(Robot).count():
            db.add_all([
                Robot(name="배송로봇 1호", robot_type="amr", status="idle"),
                Robot(name="적재 매니퓰레이터 1호", robot_type="manipulator", status="idle"),
            ])
            seeded.append("robots 2 (amr 1, manipulator 1)")
        db.commit()
        print("seeded: " + ", ".join(seeded) if seeded else "already seeded")


if __name__ == "__main__":
    main()
