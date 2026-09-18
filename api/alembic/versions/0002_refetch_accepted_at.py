"""refetch_requests.accepted_at: a gap still open after gap_check's last
attempt is kept as an accepted row, so /api/v1/status can count open gaps
(`accepted_at IS NULL`) and accepted ones from this table alone.
`bars_backfill` skips accepted rows.
"""

from __future__ import annotations

from alembic import op

revision = "0002_refetch_accepted_at"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET ROLE app_owner;")
    op.execute("ALTER TABLE refetch_requests ADD COLUMN accepted_at timestamptz;")
    op.execute("RESET ROLE;")


def downgrade() -> None:
    op.execute("SET ROLE app_owner;")
    op.execute("ALTER TABLE refetch_requests DROP COLUMN accepted_at;")
    op.execute("RESET ROLE;")
