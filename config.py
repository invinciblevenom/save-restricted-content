from os import getenv
from time import time

class PyroConf(object):
    API_ID = int(getenv("API_ID"))
    API_HASH = getenv("API_HASH")
    BOT_TOKEN = getenv("BOT_TOKEN")
    SESSION_STRING = getenv("SESSION_STRING")
    
    BOT_START_TIME = time()
    MAX_CONCURRENT_DOWNLOADS = int(getenv("MAX_CONCURRENT_DOWNLOADS", "1"))
    MAX_CONCURRENT_UPLOADS = int(getenv("MAX_CONCURRENT_UPLOADS", "1"))
    BATCH_SIZE = int(getenv("BATCH_SIZE", "1"))
    FLOOD_WAIT_DELAY = int(getenv("FLOOD_WAIT_DELAY", "5"))
