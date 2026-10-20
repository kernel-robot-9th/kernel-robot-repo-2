"""delivery_reservations → deliveries, delivery_reservation_items → delivery_items (이름 변경만)

Revision ID: 0005_rename_to_deliveries
Revises: 0004_locations
Create Date: 2026-10-14
"""
from __future__ import annotations

from alembic import op

revision = "0005_rename_to_deliveries"
down_revision = "0004_locations"
branch_labels = None
depends_on = None

# (이전 이름, 새 이름). 데이터는 그대로, 이름만 바꾼다.
TABLES = [("delivery_reservations", "deliveries"), ("delivery_reservation_items", "delivery_items")]
COLUMNS = [("delivery_items", "reservation_id", "delivery_id")]
SEQUENCES = [("delivery_reservations_id_seq", "deliveries_id_seq"), ("delivery_reservation_items_id_seq", "delivery_items_id_seq")]
INDEXES = [
    ("ix_delivery_reservations_nurse_id", "ix_deliveries_nurse_id"),
    ("ix_delivery_reservation_items_reservation_id", "ix_delivery_items_delivery_id"),
]
CONSTRAINTS = [  # (새 테이블 이름, 이전 제약 이름, 새 제약 이름) — PK·UNIQUE는 같은 이름의 인덱스도 함께 바뀐다
    ("deliveries", "delivery_reservations_pkey", "deliveries_pkey"),
    ("deliveries", "ck_delivery_reservations_status", "ck_deliveries_status"),
    ("deliveries", "delivery_reservations_nurse_id_fkey", "deliveries_nurse_id_fkey"),
    ("deliveries", "fk_delivery_reservations_destination_location_id", "fk_deliveries_destination_location_id"),
    ("delivery_items", "delivery_reservation_items_pkey", "delivery_items_pkey"),
    ("delivery_items", "ck_delivery_reservation_items_quantity", "ck_delivery_items_quantity"),
    ("delivery_items", "delivery_reservation_items_reservation_id_fkey", "delivery_items_delivery_id_fkey"),
    ("delivery_items", "delivery_reservation_items_supply_id_fkey", "delivery_items_supply_id_fkey"),
    ("delivery_items", "uq_delivery_reservation_items_reservation_supply", "uq_delivery_items_delivery_supply"),
]


def upgrade() -> None:
    for old, new in TABLES:
        op.rename_table(old, new)
    for table, old, new in COLUMNS:
        op.alter_column(table, old, new_column_name=new)
    for old, new in SEQUENCES:
        op.execute(f"ALTER SEQUENCE {old} RENAME TO {new}")
    for old, new in INDEXES:
        op.execute(f"ALTER INDEX {old} RENAME TO {new}")
    for table, old, new in CONSTRAINTS:
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {old} TO {new}")


def downgrade() -> None:
    for table, old, new in CONSTRAINTS:
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {new} TO {old}")
    for old, new in INDEXES:
        op.execute(f"ALTER INDEX {new} RENAME TO {old}")
    for old, new in SEQUENCES:
        op.execute(f"ALTER SEQUENCE {new} RENAME TO {old}")
    for table, old, new in COLUMNS:
        op.alter_column(table, new, new_column_name=old)
    for old, new in TABLES:
        op.rename_table(new, old)
