"""Kept for old import paths: the mini app is now served by `apps.core.spa`."""

from apps.core.spa import VITE_ASSET, MiniAppWhiteNoiseMiddleware

__all__ = ["VITE_ASSET", "MiniAppWhiteNoiseMiddleware"]
