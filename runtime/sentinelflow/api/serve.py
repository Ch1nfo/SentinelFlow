from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.getenv("SENTINELFLOW_API_HOST", "127.0.0.1")
    port = int(os.getenv("SENTINELFLOW_API_PORT", "8001"))
    reload_enabled = os.getenv("SENTINELFLOW_API_RELOAD", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    uvicorn.run("sentinelflow.api.app:app", host=host, port=port, reload=reload_enabled)


if __name__ == "__main__":
    main()
