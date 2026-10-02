"""Shared driver contract and input checks."""

import re


class DriverError(Exception):
    """A user-facing error without credentials or SMS contents."""


SMS = {"send", "delete"}
PIN = {
    "pin_status",
    "pin_verify",
    "pin_enable",
    "pin_disable",
    "pin_change",
}
HUAWEI = SMS | PIN | {
    "contact_add",
    "contact_delete",
}


def check_action(action: str, data: dict, capabilities: set) -> dict:
    if action not in capabilities:
        raise ValueError("Cette fonction n’est pas prise en charge par cette clé.")
    if not isinstance(data, dict):
        raise ValueError("Paramètres invalides.")
    result = {}
    if action in {"send", "contact_add"}:
        number = data.get("phone_number", "")
        if not isinstance(number, str) or not re.fullmatch(r"\+?[0-9]{6,15}", number):
            raise ValueError("Numéro invalide ; utiliser le format international.")
        result["phone_number"] = number
    if action == "send":
        text = data.get("message", "")
        if not isinstance(text, str) or not text.strip() or len(text) > 1000:
            raise ValueError("Le message doit contenir de 1 à 1000 caractères.")
        result["message"] = text
    if action in {"delete", "contact_delete"}:
        value = data.get("id")
        if isinstance(value, bool) or not re.fullmatch(r"[0-9]{1,8}", str(value)):
            raise ValueError("Index invalide.")
        result["id"] = int(value)
    if action == "contact_add":
        name = data.get("name", "")
        if not isinstance(name, str) or not name.strip() or len(name) > 50:
            raise ValueError("Le nom doit contenir de 1 à 50 caractères.")
        result["name"] = name.strip()
    if action.startswith("pin_") and action != "pin_status":
        for key in ("current_pin", "new_pin") if action == "pin_change" else ("current_pin",):
            if not isinstance(data.get(key), str) or not re.fullmatch(r"[0-9]{4,8}", data[key]):
                raise ValueError("Le PIN doit contenir de 4 à 8 chiffres.")
            result[key] = data[key]
    return result


def safe_text(value) -> str:
    return str(value).encode("utf-16-be", "surrogatepass").decode("utf-16-be", "replace")
