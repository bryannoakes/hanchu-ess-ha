import asyncio
import os
import sys

# Allow `import custom_components.hanchuess...` from the repo root without an
# install step (shared by all test modules).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# aiohttp's async DNS resolver does not work with Windows' default ProactorEventLoop.
# Switching to WindowsSelectorEventLoopPolicy restores normal DNS resolution.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


# aioresponses<=0.7.9 builds ClientResponse without the `stream_writer` keyword
# that aiohttp>=3.14 requires (Home Assistant 2026.11 pins aiohttp 3.14.5).
# Default it in tests so the mocked HTTP layer keeps working.
import inspect as _inspect

import aiohttp as _aiohttp

if "stream_writer" in _inspect.signature(_aiohttp.ClientResponse.__init__).parameters:
    from unittest.mock import MagicMock as _MagicMock

    _orig_init = _aiohttp.ClientResponse.__init__

    def _init_with_stream_writer(self, *args, **kwargs):
        kwargs.setdefault("stream_writer", _MagicMock())
        _orig_init(self, *args, **kwargs)

    _aiohttp.ClientResponse.__init__ = _init_with_stream_writer
