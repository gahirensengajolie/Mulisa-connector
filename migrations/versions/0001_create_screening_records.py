"""create screening_records

One row per screening DECISION, unique by payment reference (this is what makes a repeated
request return the stored answer instead of screening twice). Holds no names, phones or wallets.

Revision ID: 0001
Revises:
Create Date: 2026-10-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "screening_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reference", sa.String(length=64), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("recommended_action", sa.String(length=16), nullable=False),
        sa.Column("screening_id", sa.String(length=64), nullable=True),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("matched_rules", sa.JSON(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    # UNIQUE index: the database itself refuses a second row for the same reference.
    op.create_index(
        "ix_screening_records_reference",
        "screening_records",
        ["reference"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_screening_records_reference", table_name="screening_records")
    op.drop_table("screening_records")
