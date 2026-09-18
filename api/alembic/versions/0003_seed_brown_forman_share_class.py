"""share_class_rules seed for Brown-Forman (system design §3, multi-class
issuers). Only BF.B is in the index; BF.A trades too. Both classes carry
the same economic rights per share, so the total count prices at BF.B
with ratio 1, and the value is flagged approximate (multi-class).
"""

from __future__ import annotations

from alembic import op

revision = "0003_seed_brown_forman"
down_revision = "0002_refetch_accepted_at"
branch_labels = None
depends_on = None

BROWN_FORMAN_CIK = "0000014693"


def upgrade() -> None:
    op.execute("SET ROLE app_owner;")
    # share_class_rules.cik references companies; constituents_sync fills in
    # the real name and fields on its first run.
    op.execute(
        "INSERT INTO companies (cik, name, sector) "
        f"VALUES ('{BROWN_FORMAN_CIK}', 'Brown-Forman Corporation', 'Consumer Staples') "
        "ON CONFLICT (cik) DO NOTHING;"
    )
    op.execute(
        "INSERT INTO share_class_rules (cik, price_symbol, shares_unit_ratio, note) "
        f"VALUES ('{BROWN_FORMAN_CIK}', 'BF.B', 1, "
        "'Brown-Forman: Class A and Class B have equal economic value per share, so the total "
        "count prices at BF.B; BF.A is not in the index.') "
        "ON CONFLICT (cik) DO NOTHING;"
    )
    op.execute("RESET ROLE;")


def downgrade() -> None:
    op.execute("SET ROLE app_owner;")
    op.execute(f"DELETE FROM share_class_rules WHERE cik = '{BROWN_FORMAN_CIK}';")
    op.execute("RESET ROLE;")
