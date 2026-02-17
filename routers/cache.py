import time

TWO_DAYS = 60 * 60 * 24 * 2

class SimpleCache:
    def __init__(self):
        self._store = {}

    def get(self, key: str):
        entry = self._store.get(key)
        if entry and time.time() < entry["expires_at"]:
            return entry["data"]
        return None

    def set(self, key: str, data, ttl: int):
        self._store[key] = {
            "data": data,
            "expires_at": time.time() + ttl
        }

    def delete(self, key: str):
        self._store.pop(key, None)

    def clear(self):
        self._store.clear()

cache = SimpleCache()