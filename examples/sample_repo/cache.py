class Cache:
    """In-memory cache used by the example application."""

    def __init__(self):
        self.values = {}

    def get(self, key):
        """Read the cached value for a key."""
        return self.values.get(key)

    def fetch(self, key, loader):
        """Return a cached value or call the loader and save its result."""
        value = self.get(key)
        if value is None:
            value = loader(key)
            self.values[key] = value
        return value
