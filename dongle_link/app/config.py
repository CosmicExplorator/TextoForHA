"""Validated modem configuration and atomic persistence; secrets stay server-side."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

DRIVERS = {"huawei", "serial", "homeassistant"}
FIELDS = {
    "id",
    "name",
    "driver",
    "url",
    "username",
    "password",
    "port",
    "baudrate",
    "storage",
    "source",
    "inbox",
    "network_prefix",
}


def validate(data: dict, previous: dict | None = None) -> dict:
    if not isinstance(data, dict) or set(data) - FIELDS:
        raise ValueError("Configuration invalide.")
    result = dict(previous or {})
    result.update(data)
    if previous and not data.get("password"):
        result["password"] = previous.get("password", "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", str(result.get("id", ""))):
        raise ValueError("Identifiant : lettres minuscules, chiffres et tirets uniquement.")
    name = str(result.get("name", "")).strip()
    if not name or len(name) > 80:
        raise ValueError("Nom obligatoire (80 caractères maximum).")
    result["name"] = name
    driver = result.get("driver")
    if driver not in DRIVERS:
        raise ValueError("Type de connexion inconnu.")
    keep = {"id", "name", "driver"}
    if driver == "huawei":
        url = str(result.get("url", "")).strip()
        parts = urlsplit(url)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or parts.path not in {"", "/"}
        ):
            raise ValueError("Utiliser l’adresse HTTP(S) du modem, sans identifiants dans l’URL.")
        result["url"] = url.rstrip("/") + "/"
        for key in ("username", "password"):
            if not isinstance(result.get(key, ""), str) or len(result.get(key, "")) > 256:
                raise ValueError("Identifiants de connexion invalides.")
        keep |= {"url", "username", "password"}
    elif driver == "serial":
        port = str(result.get("port", ""))
        if (
            not port.startswith("/dev/serial/by-id/")
            or ".." in port.split("/")
            or len(port) > 255
            or "\x00" in port
        ):
            raise ValueError("Choisir le port AT stable dans /dev/serial/by-id/.")
        result["baudrate"] = int(result.get("baudrate", 115200))
        if result["baudrate"] not in {9600, 19200, 38400, 57600, 115200}:
            raise ValueError("Vitesse série non prise en charge.")
        result["storage"] = result.get("storage", "SM")
        if result["storage"] not in {"SM", "ME", "MT"}:
            raise ValueError("Mémoire SMS invalide.")
        keep |= {"port", "baudrate", "storage"}
    else:
        if result.get("source") not in {"huawei", "qualcomm"}:
            raise ValueError("Intégration source invalide.")
        if not re.fullmatch(r"sensor\.[a-z0-9_]+", str(result.get("inbox", ""))):
            raise ValueError("Capteur SMS invalide.")
        prefix = result.get("network_prefix", "")
        if prefix and not re.fullmatch(r"[a-z0-9_]+", prefix):
            raise ValueError("Préfixe des capteurs réseau invalide.")
        keep |= {"source", "inbox", "network_prefix"}
    return {key: value for key, value in result.items() if key in keep}


def public(config: dict) -> dict:
    return {
        **{k: v for k, v in config.items() if k != "password"},
        "has_password": bool(config.get("password")),
    }


def identity(config: dict) -> str:
    if config["driver"] == "serial":
        return "serial:" + os.path.realpath(config["port"])
    if config["driver"] == "huawei":
        return "huawei:" + config["url"].lower()
    return "ha:" + config["inbox"]


def save(path: Path, configs: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        json.dump(configs, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
