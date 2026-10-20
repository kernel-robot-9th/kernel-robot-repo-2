"""initial schema (nurses, supplies)

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-14
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('nurses',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('employee_no', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('employee_no')
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


def downgrade() -> None:
    op.drop_table('supplies')
    op.drop_table('nurses')
