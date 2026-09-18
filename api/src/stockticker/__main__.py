"""Console-script entry points (`pyproject.toml` `[project.scripts]`).

Compose invokes `uvicorn`/the worker module directly, so these exist mainly
for `uv run stockticker-api` / `uv run stockticker-worker` during local
development outside Docker.
"""

from __future__ import annotations


def run_api() -> None:
    import uvicorn

    uvicorn.run("stockticker.api.app:app", host="0.0.0.0", port=8000, reload=False)


def run_worker() -> None:
    from stockticker.worker import run

    run()


if __name__ == "__main__":
    run_api()
