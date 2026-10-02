"""Direct serial AT driver."""

from .at_modem import ATModem
from .base import PIN, SMS

REGISTRATION = {
    0: "Non enregistré",
    1: "Enregistré",
    2: "Recherche du réseau",
    3: "Accès refusé",
    4: "Inconnu",
    5: "Enregistré en itinérance",
}


class SerialDriver:
    capabilities = SMS | PIN

    def __init__(self, config):
        self.modem = ATModem(config["port"], config["baudrate"], config["storage"])

    def poll(self):
        data = self.modem.poll()
        return {
            "available": True,
            "messages": data["messages"],
            "contacts": [],
            "sim": {"status": data["sim_status"]},
            "network": {
                "Réseau": REGISTRATION.get(data["registration"], "Inconnu"),
                "Signal RSSI (dBm)": data["signal_dbm"],
                "Mémoire SMS": data["storage"],
            },
        }

    def action(self, action, data):
        if action == "send":
            self.modem.send(data["phone_number"], data["message"])
        elif action == "delete":
            self.modem.delete(data["id"])
        elif action == "pin_status":
            return {"sim": {"status": self.modem.pin_status()}}
        elif action == "pin_verify":
            self.modem.pin_verify(data["current_pin"])
        elif action == "pin_enable":
            self.modem.pin_enable(data["current_pin"])
        elif action == "pin_disable":
            self.modem.pin_disable(data["current_pin"])
        elif action == "pin_change":
            self.modem.pin_change(data["current_pin"], data["new_pin"])
        return {}
