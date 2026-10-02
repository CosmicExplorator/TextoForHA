"""Ingress-only web application with same-origin, explicit JSON mutations."""

from __future__ import annotations

import html
import json
import logging
import os
from pathlib import Path

from aiohttp import web

from .drivers.base import DriverError
from .manager import Manager

STATIC = Path(__file__).parent / "static"
MANAGER = web.AppKey("manager", Manager)
DEV = web.AppKey("dev", bool)


@web.middleware
async def access(request, handler):
    allowed = {"127.0.0.1", "::1"} if request.app[DEV] else {"172.30.32.2"}
    if request.remote not in allowed:
        raise web.HTTPForbidden(text="Ingress access only")
    if request.method not in {"GET", "HEAD"}:
        if request.headers.get("X-Dongle-Link") != "1" or request.content_type != "application/json":
            raise web.HTTPForbidden(text="JSON application requests only")
    try:
        response = await handler(request)
    except (ValueError, DriverError):
        # Validation errors are authored locally; vendor exceptions are never returned.
        raise
    response.headers.update(
        {
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; base-uri 'self'; "
            "object-src 'none'",
        }
    )
    return response


@web.middleware
async def errors(request, handler):
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except ValueError as err:
        return web.json_response({"error": str(err)}, status=400)
    except DriverError as err:
        return web.json_response({"error": str(err)}, status=502)
    except KeyError:
        return web.json_response({"error": "Modem introuvable."}, status=404)
    except Exception:
        logging.getLogger(__name__).error("Request failed: %s %s", request.method, request.path)
        return web.json_response(
            {"error": "Erreur interne ; consulter le journal de l’add-on."}, status=500
        )


async def index(request):
    base = request.headers.get("X-Ingress-Path", "").rstrip("/") + "/"
    if not base.startswith("/") or base.startswith("//"):
        raise web.HTTPBadRequest()
    text = (
        STATIC.joinpath("index.html").read_text().replace("__BASE__", html.escape(base, quote=True))
    )
    return web.Response(text=text, content_type="text/html")


async def list_modems(request):
    return web.json_response({"modems": request.app[MANAGER].snapshots(), "version": "0.1.0"})


async def configure(request):
    data = await request.json()
    modem = await request.app[MANAGER].configure(data, request.match_info.get("key"))
    return web.json_response({"modem": modem})


async def remove(request):
    await request.app[MANAGER].remove(request.match_info["key"])
    return web.json_response({"removed": True})


async def refresh(request):
    manager = request.app[MANAGER]
    manager.get(request.match_info["key"])
    return web.json_response({"modem": await manager.refresh(request.match_info["key"])})


async def action(request):
    return web.json_response(
        await request.app[MANAGER].action(
            request.match_info["key"], request.match_info["action"], await request.json()
        )
    )


def create_app(data_dir: Path, *, dev=False, manager=None):
    app = web.Application(middlewares=[access, errors], client_max_size=32 * 1024)
    app[DEV] = dev
    options = (
        json.loads((data_dir / "options.json").read_text())
        if (data_dir / "options.json").exists()
        else {}
    )
    app[MANAGER] = manager or Manager(data_dir / "modems.json", options.get("poll_interval", 60))

    async def lifecycle(app):
        await app[MANAGER].start(import_existing=options.get("import_existing", True))
        yield
        await app[MANAGER].close()

    app.cleanup_ctx.append(lifecycle)
    app.router.add_get("/", index)
    app.router.add_get("/api/modems", list_modems)
    app.router.add_post("/api/modems", configure)
    app.router.add_put("/api/modems/{key}", configure)
    app.router.add_delete("/api/modems/{key}", remove)
    app.router.add_post("/api/modems/{key}/refresh", refresh)
    app.router.add_post("/api/modems/{key}/actions/{action}", action)
    app.router.add_static("/static/", STATIC)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    development = os.environ.get("DONGLE_LINK_DEV") == "1"
    web.run_app(
        create_app(Path(os.environ.get("DONGLE_LINK_DATA", "/data")), dev=development),
        host="127.0.0.1" if development else "0.0.0.0",
        port=int(os.environ.get("DONGLE_LINK_PORT", "8099")),
        access_log=None,
    )
