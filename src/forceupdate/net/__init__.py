"""Le réseau : le client HTTP commun (``http.py``) et le cache disque (``cache.py``).

Tout ce qui interroge le réseau (registres, OSV, endoflife.date, forges) passe par
``HttpClient``. Une erreur réseau sort en ``NetworkError`` : le constat sera « non
concluant », jamais faux.
"""

from forceupdate.net.cache import Cache, CacheEntry, CacheKind, default_cache_path
from forceupdate.net.http import USER_AGENT, HttpClient, NetworkError, Response

__all__ = [
    "USER_AGENT",
    "Cache",
    "CacheEntry",
    "CacheKind",
    "HttpClient",
    "NetworkError",
    "Response",
    "default_cache_path",
]
