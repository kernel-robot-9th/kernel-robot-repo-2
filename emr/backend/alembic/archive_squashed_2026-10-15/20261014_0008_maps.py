"""maps (맵 파일 이름·맵 정보) + locations.map_id

Revision ID: 0008_maps
Revises: 0007_robots
Create Date: 2026-10-14
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0008_maps"
down_revision = "0007_robots"
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
    # 기존 장소는 맵 미지정(NULL)으로 남는다 — 맵을 등록한 뒤 PATCH /locations/{id}로 연결
    op.add_column('locations', sa.Column('map_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_locations_map_id', 'locations', 'maps', ['map_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_locations_map_id', 'locations', type_='foreignkey')
    op.drop_column('locations', 'map_id')
    op.drop_table('maps')
