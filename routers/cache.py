import os
from pathlib import Path

from routers.disk_blob_cache import DiskBlobCache

ONE_HOUR = 60 * 60
ONE_DAY = 60 * 60 * 24
TWO_DAYS = ONE_DAY * 2
SEVEN_DAYS = ONE_DAY * 7
MB = 1024 * 1024

CACHE_DIR = Path(os.getenv("DISK_BLOB_CACHE_DIR", "./cache/blobs"))
MAX_CACHE_SIZE_BYTES = int(os.getenv("DISK_BLOB_CACHE_MAX_BYTES", str(200 * MB)))
CLEANUP_INTERVAL_SECONDS = int(os.getenv("DISK_BLOB_CACHE_CLEANUP_INTERVAL_SECONDS", str(45 * 60)))

ROUTE_CACHE_TTLS = {
    "/bus-routes/stops": int(os.getenv("CACHE_TTL_BUS_ROUTES_STOPS_SECONDS", str(TWO_DAYS))),
    "/getBusRoutesData": int(os.getenv("CACHE_TTL_GET_BUS_ROUTES_DATA_SECONDS", str(TWO_DAYS))),
    "/getallbusstops": int(os.getenv("CACHE_TTL_GET_ALL_BUS_STOPS_SECONDS", str(TWO_DAYS))),
    "/getRailLinesData": int(os.getenv("CACHE_TTL_GET_RAIL_LINES_DATA_SECONDS", str(SEVEN_DAYS))),
    "/getRailStationsData": int(os.getenv("CACHE_TTL_GET_RAIL_STATIONS_DATA_SECONDS", str(SEVEN_DAYS))),
    "/getRailStationExitsData": int(os.getenv("CACHE_TTL_GET_RAIL_STATION_EXITS_DATA_SECONDS", str(SEVEN_DAYS))),
}

blob_cache = DiskBlobCache(
    cache_dir=CACHE_DIR,
    max_disk_usage_bytes=MAX_CACHE_SIZE_BYTES,
    cleanup_interval_seconds=CLEANUP_INTERVAL_SECONDS,
)
