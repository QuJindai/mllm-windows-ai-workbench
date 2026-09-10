from __future__ import annotations

import uvicorn

from config import DreamServerConfig
from app import create_app


if __name__ == "__main__":
    config = DreamServerConfig.from_environment()
    uvicorn.run(create_app(config=config), host=config.host, port=config.port, log_level="info")
