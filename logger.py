import logging
from logging import FileHandler, StreamHandler

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s - %(levelname)s] - %(message)s",
    datefmt="%I:%M:%S %p",
    handlers=[
        FileHandler("logs.txt", mode="w"),
        StreamHandler(),
    ],
)

logging.getLogger("pyrogram").setLevel(logging.ERROR)

def LOGGER(name: str) -> logging.Logger:
    return logging.getLogger(name)