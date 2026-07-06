"""HTTP-API (Flask) для віддаленого керування ПК."""

from .server import create_app, start_background

__all__ = ["create_app", "start_background"]
