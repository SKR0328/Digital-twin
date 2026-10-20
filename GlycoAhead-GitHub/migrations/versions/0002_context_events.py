"""Preserve timestamped meal/medication cells independently of CGM validity."""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("context_events", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("recording_id", sa.String(), sa.ForeignKey("recordings.id"), nullable=False),
        sa.Column("source_key", sa.String(), nullable=False), sa.Column("time", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False), sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("recording_id", "source_key"))
    op.create_index("ix_context_recording_time", "context_events", ["recording_id", "time"])


def downgrade():
    op.drop_table("context_events")
