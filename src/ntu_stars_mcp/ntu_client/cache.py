import os

MAX_CACHE_ENTRIES = 128
try:
    CACHE_TTL_SECONDS = int(os.environ.get("NTU_CACHE_TTL_SECONDS", "3600"))
except ValueError as error:
    raise RuntimeError("NTU_CACHE_TTL_SECONDS must be an integer number of seconds.") from error
if CACHE_TTL_SECONDS < 0:
    raise RuntimeError("NTU_CACHE_TTL_SECONDS must be zero or greater.")
