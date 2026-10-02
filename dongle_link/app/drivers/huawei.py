"""Huawei HiLink driver using a bounded connection per transaction."""

from huawei_lte_api.Client import Client
from huawei_lte_api.Connection import Connection

from .base import HUAWEI, safe_text

PIN_FIELDS = {
    "SimState": "État SIM",
    "PinOptState": "Protection PIN",
    "SimPinTimes": "Tentatives PIN restantes",
    "SimPukTimes": "Tentatives PUK restantes",
}
PIN_OPERATIONS = {"pin_verify": "0", "pin_enable": "1", "pin_disable": "2", "pin_change": "3"}


def contacts(payload):
    entries = payload.get("Phonebooks", {}).get("Phonebook", [])
    if isinstance(entries, dict):
        entries = [entries]
    result = []
    for entry in entries:
        fields = entry.get("Field", [])
        if isinstance(fields, dict):
            fields = [fields]
        values = {f.get("Name"): f.get("Value", "") for f in fields}
        result.append(
            {
                "id": str(entry.get("Index", "")),
                "name": safe_text(values.get("FormattedName", "")).rstrip("\x00@"),
                "phone_number": str(values.get("MobilePhone", "")),
            }
        )
    return result


class HuaweiDriver:
    capabilities = HUAWEI

    def __init__(self, config):
        self.config = config

    def connection(self):
        return Connection(
            self.config["url"],
            username=self.config.get("username") or None,
            password=self.config.get("password") or None,
            timeout=(3, 8),
        )

    def poll(self):
        with self.connection() as connection:
            client = Client(connection)
            response = client.sms.get_sms_list(page=1, read_count=50, ascending=False)
            entries = response.get("Messages", {}).get("Message", [])
            if isinstance(entries, dict):
                entries = [entries]
            result = {
                "available": True,
                "messages": [
                    {
                        "id": str(m.get("Index", "")),
                        "from": str(m.get("Phone", "")),
                        "date": str(m.get("Date", "")),
                        "content": safe_text(m.get("Content", "")),
                        "unread": str(m.get("Smstat", "1")) == "0",
                    }
                    for m in entries
                ],
                "contacts": [],
                "network": {},
                "sim": {},
            }
            # Optional endpoints vary across HiLink firmware; keep a readable inbox.
            try:
                result["contacts"] = contacts(client.pb.get_pb_list(read_count=50, save_type=1))
            except Exception:
                pass
            try:
                status = client.pin.status()
                result["sim"] = {label: status.get(key) for key, label in PIN_FIELDS.items()}
            except Exception:
                pass
            try:
                status = client.monitoring.status()
                result["network"].update(
                    {
                        "Connexion (code modem)": status.get("ConnectionStatus"),
                        "Technologie (code modem)": status.get("CurrentNetworkType"),
                        "Signal (barres)": status.get("SignalIcon"),
                    }
                )
                signal = client.device.signal()
                result["network"].update(
                    {
                        key.upper(): signal[key]
                        for key in ("rssi", "rsrp", "rsrq", "sinr")
                        if key in signal
                    }
                )
            except Exception:
                pass
            return result

    def action(self, action, data):
        with self.connection() as connection:
            client = Client(connection)
            if action == "send":
                client.sms.send_sms([data["phone_number"]], data["message"])
            elif action == "delete":
                client.sms.delete_sms(data["id"])
            elif action == "contact_add":
                client.pb._session.post_set(
                    "pb/pb-new",
                    {
                        "GroupID": 0,
                        "SaveType": 1,
                        "Field": [
                            {"Name": "FormattedName", "Value": data["name"]},
                            {"Name": "MobilePhone", "Value": data["phone_number"]},
                            *[
                                {"Name": key, "Value": ""}
                                for key in ("HomePhone", "WorkPhone", "WorkEmail")
                            ],
                        ],
                    },
                )
            elif action == "contact_delete":
                client.pb._session.post_set("pb/pb-delete", {"Index": data["id"]})
            elif action == "pin_status":
                status = client.pin.status()
                return {"sim": {label: status.get(key) for key, label in PIN_FIELDS.items()}}
            elif action in PIN_OPERATIONS:
                client.pin.operate(
                    operate_type=PIN_OPERATIONS[action],
                    current_pin=data["current_pin"],
                    new_pin=data.get("new_pin"),
                )
        return {}
