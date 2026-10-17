import anyio


class PoolAdmissionMiddleware:
    """Let at most `limit` HTTP requests into the app at once; the rest wait here.

    A request takes its database connection in get_current_user and keeps it until
    the response is sent, but it needs a worker thread again for every sync step in
    between (role check, endpoint, response validation). With more requests inside
    than pool connections, every worker thread can end up waiting for a connection
    held by requests that are waiting for a thread, and nothing moves until
    pool_timeout. With the limit at the pool size, a connection is always free for
    the thread that asks for one. Waiting requests hold neither.
    """

    def __init__(self, app, limit: int, exempt_paths: tuple[str, ...] = ("/health",)):
        self.app = app
        self.limit = limit
        self.exempt_paths = frozenset(exempt_paths)
        self._slots = None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] in self.exempt_paths:
            await self.app(scope, receive, send)
            return
        # Created on first use so it belongs to the running event loop.
        if self._slots is None:
            self._slots = anyio.Semaphore(self.limit)
        async with self._slots:
            await self.app(scope, receive, send)
