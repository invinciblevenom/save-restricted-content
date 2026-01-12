import logging
import os
from logging.handlers import RotatingFileHandler

try:
    os.remove("logs.txt")
except:
    pass

logging.basicConfig(
    level=logging.WARNING,
    format="[%(asctime)s - %(levelname)s] - %(name)s - %(message)s",
    datefmt="%d-%b-%y %I:%M:%S %p",
    handlers=[
        RotatingFileHandler("logs.txt", mode="w+", maxBytes=5000000, backupCount=5),
        logging.StreamHandler(),
    ],
)

logging.getLogger("pyrogram").setLevel(logging.ERROR)
logging.getLogger("helpers.utils").setLevel(logging.ERROR)
logging.getLogger("helpers.files").setLevel(logging.ERROR)

def LOGGER(name: str) -> logging.Logger:
    return logging.getLogger(name)