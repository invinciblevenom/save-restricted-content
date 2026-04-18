import logging
from logging.handlers import RotatingFileHandler
from logging import StreamHandler

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s - %(levelname)s] - %(message)s",
    datefmt="%I:%M:%S %p",
    handlers=[
        RotatingFileHandler("logs.txt", maxBytes=5 * 1024 * 1024, backupCount=2, mode="a"),
        StreamHandler(),
    ],
)

logging.getLogger("pyrogram").setLevel(logging.ERROR)

def LOGGER(name: str) -> logging.Logger:
    return logging.getLogger(name)