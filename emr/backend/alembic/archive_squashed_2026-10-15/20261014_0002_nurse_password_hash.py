"""nurses.password_hash (로그인)

Revision ID: 0002_nurse_password_hash
Revises: 0001_initial
Create Date: 2026-10-14
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_nurse_password_hash"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

# 기존 행에 채우는 값. bcrypt 해시 형식이 아니라 어떤 비밀번호와도 일치하지 않는다 — 비밀번호를 새로 정해야 로그인 가능.
UNUSABLE_PASSWORD_HASH = "!"


def upgrade() -> None:
    op.add_column('nurses', sa.Column('password_hash', sa.String(length=128), nullable=False, server_default=UNUSABLE_PASSWORD_HASH))
    op.alter_column('nurses', 'password_hash', server_default=None)


def downgrade() -> None:
    op.drop_column('nurses', 'password_hash')
