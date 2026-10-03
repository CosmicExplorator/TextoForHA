"""Per-modem scheduling, action routing and persistent configuration."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from . import config as settings
from .drivers.base import DriverError, check_action, safe_text
from .drivers.homeassistant import HomeAssistantDriver, discover_existing
from .drivers.huawei import HuaweiDriver
from .drivers.serial import SerialDriver

_LOGGER = logging.getLogger(__name__)

FACTORIES = {"huawei": HuaweiDriver, "serial": SerialDriver, "homeassistant": HomeAssistantDriver}


async def run_sync(function, *args):
    """Keep a device lock held even if the requesting browser disconnects."""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


def json_safe(value):
    if isinstance(value, str):
        return safe_text(value)
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    return value


@dataclass
class Device:
    config: dict
    driver: object
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    state: dict = field(
        default_factory=lambda: {
            "available": False,
            "messages": [],
            "contacts": [],
            "network": {},
            "sim": {},
            "error": "Première lecture en cours…",
            "updated_at": None,
        }
    )

    def public(self):
        return {
            "config": settings.public(self.config),
            "capabilities": sorted(self.driver.capabilities),
            **self.state,
        }


class Manager:
    def __init__(self, path: Path, interval=60, factories=None, default_modem_id=""):
        self.path = path
        self.interval = interval
        self.factories = factories or FACTORIES
        self.default_modem_id = default_modem_id
        self.devices: dict[str, Device] = {}
        self.config_lock = asyncio.Lock()
        self.stop_event = asyncio.Event()
        self.task = None

    async def start(self, import_existing=False):
        if self.path.exists():
            configs = await run_sync(lambda: json.loads(self.path.read_text()))
        elif import_existing:
            try:
                configs = await run_sync(discover_existing)
            except Exception:
                configs = []
        else:
            configs = []
        for item in configs:
            config = settings.validate(item)
            self._unique(config)
            self.devices[config["id"]] = Device(config, self.factories[config["driver"]](config))
        if not self.path.exists():
            await self._save()
        _LOGGER.info("Loaded %d modem configurations", len(self.devices))
        self.task = asyncio.create_task(self._poll_loop())

    async def close(self):
        self.stop_event.set()
        if self.task:
            await self.task

    async def _save(self):
        await run_sync(settings.save, self.path, [d.config for d in self.devices.values()])

    def _unique(self, config, replacing=None):
        for key, device in self.devices.items():
            if key == replacing:
                continue
            if key == config["id"] or settings.identity(device.config) == settings.identity(config):
                raise ValueError("Ce modem est déjà configuré.")
            if (
                device.config.get("source") == config.get("source") == "huawei"
                and device.config["driver"] == config["driver"] == "homeassistant"
            ):
                raise ValueError("L’intégration Huawei existante gère une seule clé.")

    def get(self, key):
        if key not in self.devices:
            raise KeyError("Modem introuvable.")
        return self.devices[key]

    def default(self):
        if self.default_modem_id:
            return self.get(self.default_modem_id)
        if len(self.devices) == 1:
            return next(iter(self.devices.values()))
        raise ValueError("Configurer le modem par défaut dans les options de l’add-on.")

    def snapshots(self):
        return [d.public() for d in self.devices.values()]

    async def configure(self, data, key=None):
        async with self.config_lock:
            previous = self.get(key) if key else None
            if previous and data.get("id", key) != key:
                raise ValueError("L’identifiant d’un modem ne peut pas être modifié.")
            config = settings.validate(data, previous.config if previous else None)
            self._unique(config, replacing=key)
            device = Device(config, self.factories[config["driver"]](config))
            async with previous.lock if previous else asyncio.Lock():
                self.devices[config["id"]] = device
                try:
                    await self._save()
                except Exception:
                    if previous:
                        self.devices[key] = previous
                    else:
                        self.devices.pop(config["id"], None)
                    raise
        # The configuration is durable even if the device is presently unplugged.
        asyncio.create_task(self.refresh(config["id"]))
        return device.public()

    async def remove(self, key):
        async with self.config_lock:
            device = self.get(key)
            async with device.lock:
                del self.devices[key]
                try:
                    await self._save()
                except Exception:
                    self.devices[key] = device
                    raise

    async def _poll(self, device):
        previous = device.state.get("available")
        first = device.state.get("updated_at") is None
        try:
            result = json_safe(await run_sync(device.driver.poll))
            result["updated_at"] = datetime.now(UTC).isoformat()
            result["error"] = None if result.get("available") else "Modem indisponible."
            device.state = result
        except Exception:
            device.state = {
                **device.state,
                "available": False,
                "error": "Lecture impossible. Vérifier la connexion et les réglages.",
            }

        if first or previous != device.state.get("available"):
            _LOGGER.info(
                "Modem %s: available=%s, connection=%s",
                device.config["id"],
                device.state.get("available"),
                device.config["driver"],
            )

    async def refresh(self, key):
        device = self.devices.get(key)
        if not device:
            return
        async with device.lock:
            if self.devices.get(key) is not device:
                return
            await self._poll(device)
        return device.public()

    async def action(self, key, action, data):
        device = self.get(key)
        clean = check_action(action, data, device.driver.capabilities)
        async with device.lock:
            if self.devices.get(key) is not device:
                raise ValueError("La configuration a changé ; actualiser avant de réessayer.")
            try:
                result = await run_sync(device.driver.action, action, clean)
            except DriverError:
                raise
            except Exception:
                raise DriverError(
                    "Opération refusée ou résultat incertain. Vérifier avant de réessayer."
                ) from None
            if action == "pin_status":
                device.state["sim"] = result.get("sim", {})
            else:
                await self._poll(device)
            return {"accepted": True, "result": json_safe(result), "modem": device.public()}

    async def default_action(self, action, data):
        return await self.action(self.default().config["id"], action, data)

    async def _poll_loop(self):
        while not self.stop_event.is_set():
            await asyncio.gather(*(self.refresh(key) for key in list(self.devices)))
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=self.interval)
            except TimeoutError:
                pass
