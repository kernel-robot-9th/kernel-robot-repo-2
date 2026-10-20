"""맵 이미지 업로드 — maps에 PNG 이미지·크기·원래 파일 이름. 기존 맵은 NULL(이미지 없음)

Revision ID: 0006_map_image
Revises: 0005_delivery_receipt
Create Date: 2026-10-19
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0006_map_image"
down_revision = "0005_delivery_receipt"
branch_labels = None
depends_on = None

IMAGE_ALL_OR_NONE_SQL = (
    "(image_png IS NULL AND image_width_px IS NULL AND image_height_px IS NULL AND image_file_name IS NULL)"
    " OR (image_png IS NOT NULL AND image_width_px > 0 AND image_height_px > 0 AND image_file_name IS NOT NULL)"
)


def upgrade() -> None:
    # 기존 맵은 숫자만 있어 모두 NULL로 둔다 — 화면은 격자로 그린다
    op.add_column('maps', sa.Column('image_png', sa.LargeBinary(), nullable=True))
    op.add_column('maps', sa.Column('image_width_px', sa.Integer(), nullable=True))
    op.add_column('maps', sa.Column('image_height_px', sa.Integer(), nullable=True))
    op.add_column('maps', sa.Column('image_file_name', sa.String(length=128), nullable=True))
    op.create_check_constraint('ck_maps_image_all_or_none', 'maps', IMAGE_ALL_OR_NONE_SQL)


def downgrade() -> None:
    # 올린 맵 이미지는 사라진다(숫자는 남는다)
    op.drop_constraint('ck_maps_image_all_or_none', 'maps', type_='check')
    op.drop_column('maps', 'image_file_name')
    op.drop_column('maps', 'image_height_px')
    op.drop_column('maps', 'image_width_px')
    op.drop_column('maps', 'image_png')
