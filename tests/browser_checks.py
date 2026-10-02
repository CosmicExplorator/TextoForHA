"""Browser regression checks against synthetic modems; no hardware writes.

Run with TEXTOFORHA_TEST_URL pointing to a development instance.
Every API call is intercepted before it can reach that instance.
"""

import json
import os

from playwright.sync_api import expect, sync_playwright


def fixture(key, source, text):
    capabilities = ["send", "delete"]
    if source == "huawei":
        capabilities += [
            "contact_add",
            "contact_delete",
            "pin_status",
            "pin_verify",
            "pin_enable",
            "pin_disable",
            "pin_change",
        ]
    return {
        "config": {
            "id": key,
            "name": "Huawei E3372" if source == "huawei" else "Qualcomm",
            "driver": "homeassistant",
            "source": source,
            "inbox": "sensor." + key,
            "network_prefix": key,
            "has_password": False,
        },
        "capabilities": capabilities,
        "available": True,
        "messages": [
            {
                "id": "1",
                "from": "+33612345678",
                "content": text,
                "date": "2026-10-01T12:00:00+00:00",
            }
        ],
        "contacts": [],
        "network": {"Réseau": "Enregistré", "Signal": "−51 dBm"},
        "sim": {"État SIM": "READY"},
        "updated_at": "2026-10-01T12:00:00Z",
        "error": None,
    }


def main():
    devices = [
        fixture("huawei", "huawei", "Message Huawei"),
        fixture("qualcomm", "qualcomm", '<img src=x onerror="window.injected=1"> Bonjour 😀'),
    ]
    pending = []
    calls = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1280, "height": 950})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def intercept(route):
            path = route.request.url.split("/api/", 1)[1]
            calls.append((route.request.method, path, route.request.post_data))
            if route.request.method == "GET":
                route.fulfill(json={"modems": devices, "version": "test"})
            elif "/actions/send" in path:
                pending.append(route)
            else:
                key = path.split("/")[1]
                selected = next(d for d in devices if d["config"]["id"] == key)
                route.fulfill(json={"accepted": True, "result": {}, "modem": selected})

        page.route("**/api/**", intercept)
        page.goto(os.environ.get("TEXTOFORHA_TEST_URL", "http://127.0.0.1:8108"))
        expect(page.locator("#modem")).to_have_value("huawei")
        page.select_option("#modem", "qualcomm")
        expect(page.locator(".message-text")).to_contain_text("Bonjour 😀")
        assert page.locator(".message-text img").count() == 0
        assert page.evaluate("window.injected") is None
        page.fill("#composer [name=phone]", "+33612345678")
        page.fill("#composer [name=message]", "Brouillon Qualcomm")
        page.select_option("#modem", "huawei")
        expect(page.locator("#composer [name=message]")).to_have_value("")
        page.fill("#composer [name=message]", "Brouillon Huawei")
        page.select_option("#modem", "qualcomm")
        expect(page.locator("#composer [name=message]")).to_have_value("Brouillon Qualcomm")
        page.click("#composer button[type=submit]")
        expect(page.locator("#modem")).to_be_disabled()
        expect(page.locator("[data-tab=configuration]")).to_be_disabled()
        page.wait_for_function("document.querySelector('#notice').textContent.includes('cours')")
        assert len(pending) == 1
        assert "/qualcomm/actions/send" in pending[0].request.url
        assert json.loads(pending[0].request.post_data)["message"] == "Brouillon Qualcomm"
        pending.pop().fulfill(json={"accepted": True, "modem": devices[1], "result": {}})
        expect(page.locator("#modem")).to_be_enabled()
        expect(page.locator("#composer [name=message]")).to_have_value("")
        page.click("[data-tab=contacts]")
        expect(page.locator("#content")).to_contain_text("pas encore pris en charge")
        page.click("[data-tab=network]")
        expect(page.locator("#content")).to_contain_text("−51 dBm")
        page.select_option("#modem", "huawei")
        page.click("[data-tab=configuration]")
        page.fill("#pin-form [name=current_pin]", "0123")
        # Polling must not reset secret fields or dispatch a PIN action.
        devices[0]["updated_at"] = "2026-10-01T12:01:00Z"
        page.click("#refresh")
        expect(page.locator("#pin-form [name=current_pin]")).to_have_value("0123")
        assert not any("/actions/pin_" in c[1] for c in calls)
        page.click("[data-tab=sms]")
        expect(page.locator("#composer [name=message]")).to_have_value("Brouillon Huawei")
        page.select_option("#modem", "qualcomm")
        devices[1]["messages"][0]["content"] = (
            "Bonjour ! Le modem est connecté et les SMS arrivent bien. 😀"
        )
        page.click("#refresh")
        expect(page.locator(".message-text")).to_contain_text("Le modem est connecté")
        page.screenshot(path="/tmp/textoforha-desktop.png", full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path="/tmp/textoforha-mobile.png", full_page=True)
        assert not errors, errors
        browser.close()
    print(
        "Browser checks passed: routing, in-flight lock, independent drafts, Unicode, "
        "HTML escaping, PIN preservation, capabilities and mobile layout."
    )


if __name__ == "__main__":
    main()
