"""Trace an experiment back to the conversation that produced it.

Observation, Hypothesis and Prediction all carry ``conversation_id``; Experiment
did not, so an experiment drafted from the Companion lost its origin. Additive
and nullable - existing rows are unaffected.

Revision ID: b1c4e7a90d12
Revises: 7000dcb96cc5
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b1c4e7a90d12"
down_revision = "7000dcb96cc5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("experiments", schema=None) as batch_op:
        batch_op.add_column(sa.Column("conversation_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("experiments", schema=None) as batch_op:
        batch_op.drop_column("conversation_id")
