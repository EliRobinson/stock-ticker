"""The Anthropic spend ledger, `ai_usage` (stockticker.ai.spend).

One row per Anthropic call. A row starts as a `reserved` worst-case cost,
written under an advisory lock before the call, and is `recorded` with the
usage the SDK reported once the call ends, including calls that fail partway.
A reservation the process never settled (it died mid-call) is marked
`expired` after 10 minutes and keeps its reserved, worst-case cost. The sum of
`cost_usd` is what `AI_SPEND_LIMIT_USD` is checked against.

Like 0001, this runs as the bootstrap superuser and does its DDL as
`app_owner`. The `pg_advisory_xact_lock(bigint)` grant is made as the
superuser: 0001 revoked it from PUBLIC, and the spend gate needs it.
"""

from __future__ import annotations

from alembic import op

revision = "0002_ai_usage"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET ROLE app_owner;")
    op.execute(
        """
        CREATE TABLE ai_usage (
          id bigserial PRIMARY KEY,
          created_at timestamptz NOT NULL DEFAULT now(),
          settled_at timestamptz,
          model text NOT NULL,
          state text NOT NULL CHECK (state IN ('reserved', 'recorded', 'expired')),
          input_tokens integer NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
          cache_creation_input_tokens integer NOT NULL DEFAULT 0 CHECK (cache_creation_input_tokens >= 0),
          cache_read_input_tokens integer NOT NULL DEFAULT 0 CHECK (cache_read_input_tokens >= 0),
          output_tokens integer NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
          cost_usd numeric(12,6) NOT NULL CHECK (cost_usd >= 0)
        );
        """
    )
    op.execute("CREATE INDEX ai_usage_created_at_idx ON ai_usage (created_at);")
    # 0001's default privileges would also grant DELETE; the ledger is
    # append-and-settle only, so nothing in the app can erase spend.
    op.execute("REVOKE ALL ON ai_usage FROM app_writer;")
    op.execute("GRANT SELECT, INSERT, UPDATE ON ai_usage TO app_writer;")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE ai_usage_id_seq TO app_writer;")
    op.execute("RESET ROLE;")
    op.execute("GRANT EXECUTE ON FUNCTION pg_catalog.pg_advisory_xact_lock(bigint) TO app_writer;")


def downgrade() -> None:
    op.execute("REVOKE EXECUTE ON FUNCTION pg_catalog.pg_advisory_xact_lock(bigint) FROM app_writer;")
    op.execute("SET ROLE app_owner;")
    op.execute("DROP TABLE IF EXISTS ai_usage;")
    op.execute("RESET ROLE;")
