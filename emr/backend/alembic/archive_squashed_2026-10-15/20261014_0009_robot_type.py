"""robots.robot_type (manipulator·amr)

Revision ID: 0009_robot_type
Revises: 0008_maps
Create Date: 2026-10-14
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0009_robot_type"
down_revision = "0008_maps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 기존 로봇은 지금까지 배송 로봇만 등록했으므로 amr로 채운다
    op.add_column('robots', sa.Column('robot_type', sa.String(length=16), server_default='amr', nullable=False))
    op.alter_column('robots', 'robot_type', server_default=None)
    op.create_check_constraint('ck_robots_robot_type', 'robots', "robot_type IN ('manipulator', 'amr')")


def downgrade() -> None:
    op.drop_constraint('ck_robots_robot_type', 'robots', type_='check')
    op.drop_column('robots', 'robot_type')
