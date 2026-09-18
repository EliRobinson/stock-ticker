"""The Alpaca ingest jobs (system design §4): `calendar_sync`,
`bars_backfill`, `bars_daily`, `quotes_poll`, `corporate_actions_sync`.
Registered into `stockticker.ingest.registry.JOBS` directly -- see that
module, not this package, for the `JobSpec` entries.
"""

from __future__ import annotations
