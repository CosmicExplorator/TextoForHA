"""Exercise real HTTP handlers, persistence and device isolation with fake hardware."""

import asyncio
import json
import os
import threading

import pytest
from aiohttp.test_utils import TestClient, TestServer
from app import config
from app.drivers.base import SMS, DriverError
from app.drivers.homeassistant import HomeAssistantDriver
from app.manager import Manager
from app.server import create_app


class FakeDriver:
    capabilities = SMS
    calls = []

    def __init__(self, settings):
        self.id = settings["id"]

    def poll(self):
        return {
            "available": True,
            "messages": [
                {
                    "id": "1",
                    "content": "Bonjour 😀",
                    "from": "+33612345678",
                    "date": "2026-10-01T12:00:00+00:00",
                }
            ],
            "contacts": [],
            "network": {"Signal": -51},
            "sim": {"État": "READY"},
        }

    def action(self, action, data):
        self.calls.append((self.id, action, data))
        return {}


def settings(key="one"):
    return {
        "id": key,
        "name": key,
        "driver": "huawei",
        "url": f"http://{key}.local/",
        "username": "admin",
        "password": "secret-password",
    }


@pytest.fixture(autouse=True)
def clear_calls():
    FakeDriver.calls = []


def test_config_redaction_and_atomic_private_file(tmp_path):
    private = config.validate(settings())
    assert "password" not in config.public(private)
    assert config.public(private)["has_password"]
    assert (
        config.validate({"name": "new", "password": ""}, private)["password"] == "secret-password"
    )
    path = tmp_path / "modems.json"
    config.save(path, [private])
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert json.loads(path.read_text())[0]["id"] == "one"
    assert not path.with_suffix(".tmp").exists()


@pytest.mark.parametrize(
    "patch",
    [
        {"url": "http://admin:password@modem/"},
        {"url": "file:///etc/passwd"},
        {"id": "../../other"},
        {"driver": "python"},
        {"arbitrary": "value"},
    ],
)
def test_bad_configuration_rejected(patch):
    with pytest.raises(ValueError):
        config.validate({**settings(), **patch})


def test_routing_and_no_automatic_retry(tmp_path):
    async def run():
        manager = Manager(tmp_path / "modems.json", factories={"huawei": FakeDriver})
        await manager.configure(settings("one"))
        await manager.configure(settings("two"))
        await manager.action("two", "delete", {"id": 1, "entry_id": "one"})
        assert FakeDriver.calls == [("two", "delete", {"id": 1})]
        with pytest.raises(ValueError):
            await manager.action("one", "pin_disable", {"current_pin": "1234"})
        with pytest.raises(KeyError):
            await manager.action("missing", "delete", {"id": 1})
        driver = manager.get("one").driver

        def fail(*args):
            FakeDriver.calls.append(("failed",))
            raise ValueError("sensitive vendor error")

        driver.action = fail
        with pytest.raises(DriverError) as error:
            await manager.action("one", "send", {"phone_number": "+33612345678", "message": "test"})
        assert "sensitive" not in str(error.value)
        assert FakeDriver.calls.count(("failed",)) == 1

    asyncio.run(run())


def test_duplicate_endpoint_is_rejected(tmp_path):
    async def run():
        manager = Manager(tmp_path / "modems.json", factories={"huawei": FakeDriver})
        await manager.configure(settings("one"))
        with pytest.raises(ValueError):
            await manager.configure({**settings("two"), "url": "http://one.local/"})

    asyncio.run(run())


def test_failed_refresh_does_not_turn_accepted_send_into_failure(tmp_path):
    async def run():
        manager = Manager(tmp_path / "modems.json", factories={"huawei": FakeDriver})
        await manager.configure(settings())

        def fail():
            raise OSError("offline")

        manager.get("one").driver.poll = fail
        result = await manager.action(
            "one", "send", {"phone_number": "+33612345678", "message": "test"}
        )
        assert result["accepted"]
        assert not result["modem"]["available"]
        assert len(FakeDriver.calls) == 1

    asyncio.run(run())


def test_browser_disconnect_cannot_release_lock_during_serial_action(tmp_path):
    async def run():
        manager = Manager(tmp_path / "modems.json", factories={"huawei": FakeDriver})
        await manager.configure(settings())
        await manager.refresh("one")
        started, release = threading.Event(), threading.Event()

        def slow(*args):
            started.set()
            release.wait(3)
            return {}

        manager.get("one").driver.action = slow
        task = asyncio.create_task(manager.action("one", "delete", {"id": 1}))
        await asyncio.to_thread(started.wait, 2)
        task.cancel()
        await asyncio.sleep(0.01)
        assert manager.get("one").lock.locked()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not manager.get("one").lock.locked()

    asyncio.run(run())


def test_bridge_requires_actual_entry_id_and_ignores_callers_target(monkeypatch):
    driver = HomeAssistantDriver({"source": "qualcomm", "inbox": "sensor.test"})
    sent = []
    monkeypatch.setattr(driver.api, "state", lambda _: {"attributes": {"entry_id": "correct"}})
    monkeypatch.setattr(driver.api, "request", lambda *args: sent.append(args) or {})
    driver.action("delete", {"id": 7, "entry_id": "wrong"})
    assert sent[0][2] == {"entry_id": "correct", "message_id": 7}
    monkeypatch.setattr(driver.api, "state", lambda _: {"attributes": {}})
    with pytest.raises(DriverError):
        driver.action("delete", {"id": 7})
    assert len(sent) == 1


def test_real_http_routes_and_ingress_restrictions(tmp_path):
    async def run():
        (tmp_path / "options.json").write_text('{"import_existing": false}')
        manager = Manager(tmp_path / "modems.json", factories={"huawei": FakeDriver})
        app = create_app(tmp_path, dev=True, manager=manager)
        async with TestClient(TestServer(app)) as client:
            assert (await client.get("/")).status == 200
            assert (await client.post("/api/modems", json=settings())).status == 403
            headers = {"X-Dongle-Link": "1"}
            response = await client.post("/api/modems", json=settings(), headers=headers)
            assert response.status == 200
            assert "secret-password" not in await response.text()
            response = await client.post("/api/modems/one/refresh", json={}, headers=headers)
            assert response.status == 200
            response = await client.get("/api/modems")
            body = await response.json()
            assert body["modems"][0]["messages"][0]["content"] == "Bonjour 😀"
            assert "password" not in body["modems"][0]["config"]
            assert (
                await client.post("/api/modems/one/actions/pin_disable", json={}, headers=headers)
            ).status == 400
            assert (
                await client.post(
                    "/api/modems/missing/actions/delete", json={"id": 1}, headers=headers
                )
            ).status == 404
            assert not FakeDriver.calls
        restricted = create_app(
            tmp_path,
            dev=False,
            manager=Manager(tmp_path / "modems.json", factories={"huawei": FakeDriver}),
        )
        async with TestClient(TestServer(restricted)) as client:
            assert (await client.get("/")).status == 403

    asyncio.run(run())
