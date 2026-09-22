"""Round-robin reverse proxy: simulates one service entry point in front of
two vLLM instances (each exposing its own /metrics) — the shape of a
PD-disaggregated deployment from the client's perspective.

Listens on :9150 and alternates every request between the two backends.
Streaming (SSE) responses are passed through chunk-by-chunk.
"""
import itertools

from aiohttp import ClientSession, ClientTimeout, web

BACKENDS = ["http://127.0.0.1:9155", "http://127.0.0.1:9156"]
PORT = 9150

# Hop-by-hop headers (never forwarded); host/accept-encoding cause trouble too.
REQ_STRIP = {
    "connection", "keep-alive", "host", "transfer-encoding",
    "upgrade", "te", "trailer", "accept-encoding",
}
RESP_STRIP = {
    "connection", "keep-alive", "transfer-encoding",
    "content-length", "upgrade", "te", "trailer",
}

_rr = itertools.cycle(BACKENDS)


async def forward(request: web.Request) -> web.StreamResponse:
    backend = next(_rr)
    body = await request.read()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in REQ_STRIP}
    sess: ClientSession = request.app["client"]
    async with sess.request(
        request.method, backend + str(request.rel_url),
        data=body, headers=headers,
    ) as up:
        out_headers = {k: v for k, v in up.headers.items() if k.lower() not in RESP_STRIP}
        out = web.StreamResponse(status=up.status, headers=out_headers)
        await out.prepare(request)
        async for chunk in up.content.iter_any():
            await out.write(chunk)
        await out.write_eof()
        return out


async def on_startup(app):
    app["client"] = ClientSession(timeout=ClientTimeout(total=None, sock_read=600))


async def on_cleanup(app):
    await app["client"].close()


def make_app() -> web.Application:
    app = web.Application(client_max_size=64 * 1024 * 1024)
    app.router.add_route("*", "/{tail:.*}", forward)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


if __name__ == "__main__":
    web.run_app(make_app(), host="0.0.0.0", port=PORT, print=None)
