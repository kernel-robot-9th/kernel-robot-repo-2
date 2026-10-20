"""기준 스키마: 2026-10-14 마이그레이션 0001~0014를 하나로 합침 (운영 DB가 생기기 전)

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-15

합치기 전 파일은 alembic/archive_squashed_2026-10-15/ 에 보관했다 (alembic이 읽지 않는 폴더).
0001~0014를 차례로 적용한 DB와 스키마가 같다 (pg_dump 비교, 컬럼 순서만 다름).
0014까지 적용된 기존 DB는 이 리비전을 모르므로 docker compose down -v 로 다시 만든다.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('maps',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('file_name', sa.String(length=128), nullable=False),
    sa.Column('resolution_m_per_pixel', sa.Float(), nullable=False),
    sa.Column('origin_x_m', sa.Float(), nullable=False),
    sa.Column('origin_y_m', sa.Float(), nullable=False),
    sa.Column('origin_yaw_rad', sa.Float(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('resolution_m_per_pixel > 0', name='ck_maps_resolution_m_per_pixel'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('file_name'),
    sa.UniqueConstraint('name')
    )
    op.create_table('nurses',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('employee_no', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('password_hash', sa.String(length=128), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('employee_no')
    )
    op.create_table('robots',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('robot_type', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("robot_type IN ('manipulator', 'amr')", name='ck_robots_robot_type'),
    sa.CheckConstraint("status IN ('idle', 'delivering', 'charging', 'maintenance')", name='ck_robots_status'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('supplies',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('category', sa.String(length=16), nullable=False),
    sa.Column('requestable_by', sa.String(length=16), nullable=False),
    sa.Column('stock_qty', sa.Integer(), nullable=False),
    sa.Column('expiry_date', sa.Date(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("category IN ('medication', 'supply')", name='ck_supplies_category'),
    sa.CheckConstraint("requestable_by IN ('nurse', 'patient')", name='ck_supplies_requestable_by'),
    sa.CheckConstraint('stock_qty >= 0', name='ck_supplies_stock_qty'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_table('locations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('map_x_m', sa.Float(), nullable=True),
    sa.Column('map_y_m', sa.Float(), nullable=True),
    sa.Column('map_yaw_rad', sa.Float(), nullable=True),
    sa.Column('map_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('(map_x_m IS NULL AND map_y_m IS NULL AND map_yaw_rad IS NULL) OR (map_x_m IS NOT NULL AND map_y_m IS NOT NULL AND map_yaw_rad IS NOT NULL)', name='ck_locations_map_pose_all_or_none'),
    sa.ForeignKeyConstraint(['map_id'], ['maps.id'], name='fk_locations_map_id'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('deliveries',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('nurse_id', sa.Integer(), nullable=False),
    sa.Column('destination_location_id', sa.Integer(), nullable=False),
    sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('reserved', 'cancelled')", name='ck_deliveries_status'),
    sa.ForeignKeyConstraint(['destination_location_id'], ['locations.id'], name='fk_deliveries_destination_location_id'),
    sa.ForeignKeyConstraint(['nurse_id'], ['nurses.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_deliveries_nurse_id'), 'deliveries', ['nurse_id'], unique=False)
    op.create_table('delivery_items',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('delivery_id', sa.Integer(), nullable=False),
    sa.Column('supply_id', sa.Integer(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.CheckConstraint('quantity > 0', name='ck_delivery_items_quantity'),
    sa.ForeignKeyConstraint(['delivery_id'], ['deliveries.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['supply_id'], ['supplies.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('delivery_id', 'supply_id', name='uq_delivery_items_delivery_supply')
    )
    op.create_index(op.f('ix_delivery_items_delivery_id'), 'delivery_items', ['delivery_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_delivery_items_delivery_id'), table_name='delivery_items')
    op.drop_table('delivery_items')
    op.drop_index(op.f('ix_deliveries_nurse_id'), table_name='deliveries')
    op.drop_table('deliveries')
    op.drop_table('locations')
    op.drop_table('supplies')
    op.drop_table('robots')
    op.drop_table('nurses')
    op.drop_table('maps')
