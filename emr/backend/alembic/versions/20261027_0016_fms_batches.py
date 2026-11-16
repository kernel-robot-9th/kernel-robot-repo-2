"""FMS API v1 연동 2단계 — fms_batches (FMS 묶음을 실제 OMX로 싣는 진행)

사용자 결정(2026-10-27): "OMX만 실제로 변경하고 2개 약품해서 진행", 양팔 탑재(/pinky — 정밀 주차 뒤 내려놓기)까지 실제,
명령은 POST /command {"command": {"blue": N, "green": N}, "request_id"} — 묶음 하나에 한 번.
FMS batch_assigned 때 한 줄 만들고, 주기 작업(services/fms_omx.py)이 OMX /status를 보며 /command·FMS ready·/pinky·FMS loaded를 보낸다.
계약: docs/api_contract_delivery_2026-10-20.md 10.4

Revision ID: 0016_fms_batches
Revises: 0015_fms_orders
Create Date: 2026-10-27
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0016_fms_batches"
down_revision = "0015_fms_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fms_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.String(length=32), nullable=False),
        sa.Column("fms_robot_number", sa.Integer(), nullable=False),
        sa.Column("blue_count", sa.Integer(), nullable=False),
        sa.Column("green_count", sa.Integer(), nullable=False),
        sa.Column("step", sa.String(length=16), nullable=False),
        sa.Column("omx_request_id", sa.String(length=64), nullable=True),
        sa.Column("error", sa.String(length=255), nullable=True),
        sa.Column("ready_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("at_pharmacy_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("loaded_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("step_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "step IN ('pick', 'picking', 'ready', 'called', 'pinky', 'loading', 'loaded', 'delivering', 'failed')",
            name="ck_fms_batches_step",
        ),
        sa.CheckConstraint("blue_count >= 0 AND green_count >= 0 AND blue_count + green_count >= 1", name="ck_fms_batches_counts"),
    )
    op.create_index("ix_fms_batches_batch_id", "fms_batches", ["batch_id"])


def downgrade() -> None:
    op.drop_index("ix_fms_batches_batch_id", table_name="fms_batches")
    op.drop_table("fms_batches")
