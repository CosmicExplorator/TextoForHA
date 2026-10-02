"""Compatibility bridge: reuse installed integrations without opening their devices."""

import os

import requests

from .base import HUAWEI, PIN, SMS, DriverError
from .serial import REGISTRATION

SERVICE_NAMES = {
    "contact_add": "add_contact",
    "contact_delete": "delete_contact",
    "pin_status": "get_pin_status",
    "pin_verify": "verify_pin",
    "pin_enable": "enable_pin",
    "pin_disable": "disable_pin",
    "pin_change": "change_pin",
}


class CoreAPI:
    def __init__(self):
        self.token = os.environ.get("SUPERVISOR_TOKEN", "")

    def request(self, method, path, data=None):
        if not self.token:
            raise DriverError("L’accès à l’API Home Assistant est indisponible.")
        response = requests.request(
            method,
            "http://supervisor/core/api/" + path,
            headers={"Authorization": "Bearer " + self.token},
            json=data,
            timeout=(3, 20),
        )
        response.raise_for_status()
        return response.json()

    def state(self, entity):
        return self.request("GET", "states/" + entity)


class HomeAssistantDriver:
    def __init__(self, config):
        self.config = config
        self.api = CoreAPI()
        self.capabilities = HUAWEI if config["source"] == "huawei" else SMS | PIN

    def poll(self):
        states = {s["entity_id"]: s for s in self.api.request("GET", "states")}
        inbox = states.get(self.config["inbox"])
        if not inbox:
            raise DriverError("Le capteur SMS configuré est introuvable.")
        attrs = inbox.get("attributes", {})
        data = {
            "available": inbox["state"] not in {"unavailable", "unknown"},
            "messages": attrs.get("messages", []),
            "contacts": attrs.get("contacts", []),
            "sim": attrs.get("pin_status", {}),
            "network": {},
        }
        prefix = self.config.get("network_prefix", "")
        if prefix:
            if self.config["source"] == "qualcomm":
                fields = {"sim": "Carte SIM", "signal": "Signal RSSI", "reseau": "Réseau"}
            else:
                fields = {
                    "nom_de_l_operateur": "Opérateur",
                    "mode": "Technologie",
                    "rssi": "RSSI",
                    "rsrp": "RSRP",
                    "rsrq": "RSRQ",
                    "sinr": "SINR",
                }
            for suffix, label in fields.items():
                state = states.get(f"sensor.{prefix}_{suffix}", {})
                value = state.get("state", "unavailable")
                if value in {"unavailable", "unknown"}:
                    value = "Indisponible"
                elif suffix == "reseau":
                    value = REGISTRATION.get(int(value), value)
                unit = state.get("attributes", {}).get("unit_of_measurement", "")
                data["network"][label] = f"{value} {unit}".strip()
                if suffix == "sim":
                    data["sim"] = {"État SIM": value}
        return data

    def action(self, action, data):
        source = self.config["source"]
        if source == "qualcomm" and action == "pin_status":
            prefix = self.config.get("network_prefix", "qualcomm_sms")
            state = self.api.state(f"sensor.{prefix}_sim")
            return {"sim": {"État SIM": state.get("state", "Indisponible")}}
        domain = "huawei_sms" if source == "huawei" else "qualcomm_sms"
        payload = dict(data)
        if source == "qualcomm":
            state = self.api.state(self.config["inbox"])
            entry_id = state.get("attributes", {}).get("entry_id")
            if not entry_id:
                raise DriverError("L’identifiant de cette intégration Qualcomm est absent.")
            payload["entry_id"] = entry_id
        if action in {"delete", "contact_delete"}:
            payload["message_id" if action == "delete" else "contact_id"] = payload.pop("id")
        service = action if source == "qualcomm" and action.startswith("pin_") else SERVICE_NAMES.get(action, action)
        response = self.api.request(
            "POST",
            f"services/{domain}/{service}" + ("?return_response" if action == "pin_status" else ""),
            payload,
        )
        if action == "pin_status":
            return {"sim": response.get("service_response", {})}
        return {}


def discover_existing():
    """Import only known existing integrations, never claim an unknown serial port."""
    states = {s["entity_id"]: s for s in CoreAPI().request("GET", "states")}
    configs = []
    for source, entity, prefix, name in (
        ("huawei", "sensor.sms_huawei_e3372", "local_e3372", "Huawei E3372"),
        ("qualcomm", "sensor.qualcomm_sms_sms", "qualcomm_sms", "Qualcomm"),
    ):
        if entity in states:
            configs.append(
                {
                    "id": source,
                    "name": name,
                    "driver": "homeassistant",
                    "source": source,
                    "inbox": entity,
                    "network_prefix": prefix,
                }
            )
    return configs
