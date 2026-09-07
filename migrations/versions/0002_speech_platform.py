"""Add speech capabilities without rewriting or deleting existing task data."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("jobs", "asset_id", existing_type=sa.String(32), nullable=True)
    op.add_column(
        "jobs", sa.Column("kind", sa.String(32), nullable=False, server_default="transcription")
    )
    op.add_column(
        "jobs", sa.Column("deployment_id", sa.String(100), nullable=False, server_default="default")
    )
    op.add_column("jobs", sa.Column("input", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("jobs", sa.Column("capture_key", sa.String(512)))
    op.add_column("jobs", sa.Column("audio_key", sa.String(512)))
    op.add_column("attempts", sa.Column("deployment", sa.JSON()))
    op.add_column("attempts", sa.Column("capture_key", sa.String(512)))
    for name in ("kind", "deployment_id", "input"):
        op.alter_column("jobs", name, server_default=None)
    op.create_index("jobs_deployment_state", "jobs", ["deployment_id", "state"])
    op.create_check_constraint(
        "jobs_capability_asset",
        "jobs",
        "(kind = 'transcription' AND asset_id IS NOT NULL) OR "
        "(kind = 'synthesis' AND asset_id IS NULL)",
    )


def downgrade():
    # A downgrade would discard synthesis inputs and recovery evidence.
    raise RuntimeError("Restore a reviewed backup to downgrade speech task data")
