"""robots (등록·이름·상태)

Revision ID: 0007_robots
Revises: 0006_delivery_dispatch
Create Date: 2026-10-14
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0007_robots"
down_revision = "0006_delivery_dispatch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('robots',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('idle', 'delivering', 'charging', 'maintenance')", name='ck_robots_status'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )


def downgrade() -> None:
    op.drop_table('robots')
