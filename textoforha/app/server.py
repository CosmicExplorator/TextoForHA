"""Serveur FastAPI de TextoForHA, accessible uniquement via Home Assistant."""

from __future__ import annotations

import html
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Body, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .drivers.base import DriverError
from .manager import Manager

STATIC = Path(__file__).parent / "static"
VERSION = "2026-10.2"
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; "
    "connect-src 'self'; img-src 'self' data:; base-uri 'self'; object-src 'none'",
}


def read_options(data_dir: Path) -> dict[str, Any]:
    """Lit les options validées par le Supervisor, sans les exposer au navigateur."""
    path = data_dir / "options.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    return data if isinstance(data, dict) else {}


def allowed_source(request: Request, development: bool) -> bool:
    """Accepte Ingress et Home Assistant Core, mais jamais le réseau local."""
    host = request.client.host if request.client else ""
    if development:
        return host in {"127.0.0.1", "::1"}
    # .2 est le proxy Ingress ; .1 correspond aux appels internes du Core.
    return host in {"172.30.32.1", "172.30.32.2"}


def json_error(message: str, status_code: int) -> JSONResponse:
    """Produit toutes les erreurs d'API avec le même format, sans fuite technique."""
    return JSONResponse({"error": message}, status_code=status_code)


def create_app(data_dir: Path, *, dev: bool = False, manager: Manager | None = None) -> FastAPI:
    """Construit l'application et raccorde un gestionnaire de modems isolé."""
    options = read_options(data_dir)
    logging.getLogger().setLevel(
        getattr(logging, str(options.get("log_level", "info")).upper(), logging.INFO)
    )
    modem_manager = manager or Manager(
        data_dir / "modems.json",
        options.get("poll_interval", 60),
        default_modem_id=options.get("default_modem_id", ""),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await modem_manager.start(import_existing=options.get("import_existing", False))
        yield
        await modem_manager.close()

    app = FastAPI(title="TextoForHA", version=VERSION, lifespan=lifespan)
    app.state.manager = modem_manager
    app.state.development = dev

    @app.middleware("http")
    async def protect(request: Request, call_next):
        """Applique les règles Ingress avant toute lecture du corps de requête."""
        if not allowed_source(request, app.state.development):
            return PlainTextResponse("Ingress access only", status_code=403)
        if request.method not in {"GET", "HEAD"}:
            content_type = request.headers.get("content-type", "").split(";", 1)[0]
            if request.headers.get("X-TextoForHA") != "1" or content_type != "application/json":
                return PlainTextResponse("JSON application requests only", status_code=403)
            if int(request.headers.get("content-length", "0") or 0) > 32 * 1024:
                return json_error("Requête trop volumineuse.", 413)
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    @app.exception_handler(ValueError)
    async def value_error(_: Request, error: ValueError):
        return json_error(str(error), 400)

    @app.exception_handler(DriverError)
    async def driver_error(_: Request, error: DriverError):
        return json_error(str(error), 502)

    @app.exception_handler(KeyError)
    async def key_error(_: Request, __: KeyError):
        return json_error("Modem introuvable.", 404)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, _: Exception):
        logging.getLogger(__name__).exception(
            "Échec de la requête %s %s", request.method, request.url.path
        )
        return json_error("Erreur interne ; consulter le journal de l’add-on.", 500)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index(request: Request):
        """Retourne l'interface avec le préfixe Ingress contrôlé par Home Assistant."""
        base = request.headers.get("X-Ingress-Path", "").rstrip("/") + "/"
        if not base.startswith("/") or base.startswith("//"):
            raise ValueError("Chemin Ingress invalide.")
        text = STATIC.joinpath("index.html").read_text().replace(
            "__BASE__", html.escape(base, quote=True)
        )
        return HTMLResponse(text)

    @app.get("/api/modems")
    async def list_modems():
        """Liste les modems et leur état sans jamais inclure les mots de passe."""
        return {"modems": modem_manager.snapshots(), "version": VERSION}

    @app.post("/api/modems")
    async def configure(payload: object = Body(...)):
        """Ajoute un modem après validation par le gestionnaire."""
        return {"modem": await modem_manager.configure(payload)}

    @app.put("/api/modems/{key}")
    async def update_modem(key: str, payload: object = Body(...)):
        """Met à jour la configuration d'un modem existant."""
        return {"modem": await modem_manager.configure(payload, key)}

    @app.delete("/api/modems/{key}")
    async def remove_modem(key: str):
        """Retire seulement la configuration TextoForHA du modem demandé."""
        await modem_manager.remove(key)
        return {"removed": True}

    @app.post("/api/modems/{key}/refresh")
    async def refresh_modem(key: str, _: object = Body(...)):
        """Force une lecture immédiate du modem demandé."""
        modem_manager.get(key)
        return {"modem": await modem_manager.refresh(key)}

    @app.post("/api/modems/{key}/actions/{action}")
    async def modem_action(key: str, action: str, payload: object = Body(...)):
        """Exécute une action explicite sur un modem donné."""
        return await modem_manager.action(key, action, payload)

    @app.post("/api/actions/{action}")
    async def default_modem_action(action: str, payload: object = Body(...)):
        """Exécute une action sur le modem par défaut des options de l'add-on."""
        return await modem_manager.default_action(action, payload)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    development = os.environ.get("TEXTOFORHA_DEV") == "1"
    uvicorn.run(
        create_app(Path(os.environ.get("TEXTOFORHA_DATA", "/data")), dev=development),
        host="127.0.0.1" if development else "0.0.0.0",
        port=int(os.environ.get("TEXTOFORHA_PORT", "8099")),
        access_log=False,
    )
