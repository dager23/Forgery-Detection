"""ASGI entrypoint: ``uvicorn docauth.main:app``."""

import logging

from docauth.app import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = create_app()
