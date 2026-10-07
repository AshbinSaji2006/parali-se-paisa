from __future__ import annotations

import os
import uvicorn


if __name__ == "__main__":
    uvicorn.run("src.api.main:app", host=os.getenv("API_HOST", "127.0.0.1"),
                port=int(os.getenv("API_PORT", "8000")), reload=False)
