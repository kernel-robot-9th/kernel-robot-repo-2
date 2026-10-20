"""delivery_reservations, delivery_reservation_items (배송 일정 예약)

Revision ID: 0003_delivery_reservations
Revises: 0002_nurse_password_hash
Create Date: 2026-10-14
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_delivery_reservations"
down_revision = "0002_nurse_password_hash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('delivery_reservations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('nurse_id', sa.Integer(), nullable=False),
    sa.Column('destination', sa.String(length=64), nullable=False),
    sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('reserved', 'cancelled')", name='ck_delivery_reservations_status'),
    sa.ForeignKeyConstraint(['nurse_id'], ['nurses.id']),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_delivery_reservations_nurse_id'), 'delivery_reservations', ['nurse_id'], unique=False)
    op.create_table('delivery_reservation_items',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('reservation_id', sa.Integer(), nullable=False),
    sa.Column('supply_id', sa.Integer(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.CheckConstraint('quantity > 0', name='ck_delivery_reservation_items_quantity'),
    sa.ForeignKeyConstraint(['reservation_id'], ['delivery_reservations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['supply_id'], ['supplies.id']),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('reservation_id', 'supply_id', name='uq_delivery_reservation_items_reservation_supply')
    )
    op.create_index(op.f('ix_delivery_reservation_items_reservation_id'), 'delivery_reservation_items', ['reservation_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_delivery_reservation_items_reservation_id'), table_name='delivery_reservation_items')
    op.drop_table('delivery_reservation_items')
    op.drop_index(op.f('ix_delivery_reservations_nurse_id'), table_name='delivery_reservations')
    op.drop_table('delivery_reservations')
