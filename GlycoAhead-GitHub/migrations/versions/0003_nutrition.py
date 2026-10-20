"""Versioned nutrition lookup and inspectable food-reference rows."""
from alembic import op
import sqlalchemy as sa
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("nutrition_catalogs", sa.Column("id", sa.String(), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("created_at", sa.String(), nullable=False))
    op.create_table("nutrition_references", sa.Column("id", sa.String(), primary_key=True),
        sa.Column("catalog_id", sa.String(), sa.ForeignKey("nutrition_catalogs.id"), nullable=False),
        sa.Column("reference_key", sa.String(), nullable=False), sa.Column("description", sa.String(), nullable=False),
        sa.Column("nutrients", sa.JSON(), nullable=False), sa.Column("portions", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False), sa.UniqueConstraint("catalog_id", "reference_key"))
    op.create_index("ix_nutrition_references_catalog_id", "nutrition_references", ["catalog_id"])


def downgrade():
    op.drop_table("nutrition_references")
    op.drop_table("nutrition_catalogs")
