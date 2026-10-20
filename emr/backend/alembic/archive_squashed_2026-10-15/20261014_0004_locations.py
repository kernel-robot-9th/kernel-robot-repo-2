"""locations + delivery_reservations.destination → destination_location_id

Revision ID: 0004_locations
Revises: 0003_delivery_reservations
Create Date: 2026-10-14
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004_locations"
down_revision = "0003_delivery_reservations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('locations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('map_x_m', sa.Float(), nullable=True),
    sa.Column('map_y_m', sa.Float(), nullable=True),
    sa.Column('map_yaw_rad', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('(map_x_m IS NULL AND map_y_m IS NULL AND map_yaw_rad IS NULL) OR (map_x_m IS NOT NULL AND map_y_m IS NOT NULL AND map_yaw_rad IS NOT NULL)', name='ck_locations_map_pose_all_or_none'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.add_column('delivery_reservations', sa.Column('destination_location_id', sa.Integer(), nullable=True))
    # 기존 예약의 자유 입력 문자열을 좌표 미등록 장소로 옮긴다
    op.execute("INSERT INTO locations (name) SELECT DISTINCT destination FROM delivery_reservations")
    op.execute(
        "UPDATE delivery_reservations SET destination_location_id = locations.id "
        "FROM locations WHERE locations.name = delivery_reservations.destination"
    )
    op.alter_column('delivery_reservations', 'destination_location_id', nullable=False)
    op.create_foreign_key(
        'fk_delivery_reservations_destination_location_id', 'delivery_reservations', 'locations',
        ['destination_location_id'], ['id'],
    )
    op.drop_column('delivery_reservations', 'destination')


def downgrade() -> None:
    op.add_column('delivery_reservations', sa.Column('destination', sa.String(length=64), nullable=True))
    op.execute(
        "UPDATE delivery_reservations SET destination = locations.name "
        "FROM locations WHERE locations.id = delivery_reservations.destination_location_id"
    )
    op.alter_column('delivery_reservations', 'destination', nullable=False)
    op.drop_constraint('fk_delivery_reservations_destination_location_id', 'delivery_reservations', type_='foreignkey')
    op.drop_column('delivery_reservations', 'destination_location_id')
    op.drop_table('locations')
