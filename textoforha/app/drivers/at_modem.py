"""Bounded AT transactions, independent of the Huawei HTTP client.

All public operations run in HA's executor. A lock covers the entire transaction,
including a CMGS prompt and its payload. No command that sends a message is retried.
"""

from __future__ import annotations

import re
import threading
import time
from contextlib import contextmanager
from typing import Any

import serial
from gsmmodem.pdu import Concatenation, decodeSmsPdu, encodeSmsSubmitPdu

PHONE_RE = re.compile(r"\+?[0-9]{6,15}\Z")
PIN_RE = re.compile(r"[0-9]{4,8}\Z")
MAX_RESPONSE = 256 * 1024


class ModemError(Exception):
    """A safe error that never includes SMS contents, PINs or identifiers."""


def parse_inbox(lines: list[str]) -> list[dict[str, Any]]:
    """Decode PDU records, keeping modem indices for explicit deletion.

    URCs may occur between records. Invalid PDUs fail the refresh rather than
    silently making stored messages disappear. Concatenated parts are exposed
    individually with their sequence information.
    """
    messages = []
    pending: tuple[int, int] | None = None
    for line in lines:
        match = re.match(r"^\+CMGL:\s*(\d+),(\d+),", line)
        if match:
            if pending is not None:
                raise ModemError("Réponse SMS incomplète.")
            pending = (int(match[1]), int(match[2]))
        elif pending is not None and re.fullmatch(r"(?:[0-9A-Fa-f]{2})+", line):
            index, status = pending
            pending = None
            try:
                decoded = decodeSmsPdu(line)
            except Exception:
                raise ModemError("Un SMS ne peut pas être décodé.") from None
            if decoded["type"] != "SMS-DELIVER":
                continue
            message = {
                "id": str(index),
                "from": decoded["number"],
                "date": decoded["time"].isoformat(),
                # The PDU library returns UTF-16 surrogate code units for emoji.
                # Combine valid pairs and replace lone halves before HA JSON encoding.
                "content": decoded["text"]
                .encode("utf-16-be", errors="surrogatepass")
                .decode("utf-16-be", errors="replace"),
                "unread": status == 0,
            }
            for header in decoded.get("udh", []):
                if isinstance(header, Concatenation):
                    message["part"] = header.number
                    message["parts"] = header.parts
                    message["reference"] = header.reference
            messages.append(message)
    if pending is not None:
        raise ModemError("Réponse SMS incomplète.")
    return sorted(messages, key=lambda msg: msg["date"], reverse=True)


def response_value(lines: list[str], prefix: str) -> str:
    """Extract a solicited response without exposing unrelated modem data."""
    for line in lines:
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    raise ModemError("Réponse du modem incomplète.")


class ATModem:
    """One explicitly selected serial port; never scans other USB devices."""

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        storage: str = "SM",
    ) -> None:
        if storage not in {"SM", "ME", "MT"}:
            raise ValueError("Mémoire SMS invalide.")
        self.port = port
        self.baudrate = baudrate
        self.storage = storage
        self._lock = threading.Lock()

    @contextmanager
    def _session(self):
        with self._lock:
            try:
                with serial.Serial(
                    self.port,
                    self.baudrate,
                    timeout=0.2,
                    write_timeout=3,
                    exclusive=True,
                ) as connection:
                    # Exit an abandoned SMS prompt without submitting its payload.
                    connection.write(b"\x1b\r")
                    # Drain the cancelled prompt before the first AT command.
                    deadline = time.monotonic() + 2
                    while time.monotonic() < deadline and connection.read(256):
                        pass
                    connection.reset_input_buffer()
                    self._command(connection, "AT")
                    yield connection
            except (serial.SerialException, OSError):
                raise ModemError("Port série inaccessible ou occupé ; fermer microcom.") from None

    def _read(self, connection, *, prompt=False, timeout=8) -> list[str]:
        deadline = time.monotonic() + timeout
        buffer = bytearray()
        lines: list[str] = []
        total = 0
        while time.monotonic() < deadline:
            chunk = connection.read(1)
            if not chunk:
                continue
            buffer.extend(chunk)
            total += len(chunk)
            if total > MAX_RESPONSE:
                raise ModemError("Réponse du modem trop longue.")
            if prompt and bytes(buffer).strip() == b">":
                return lines
            if chunk != b"\n":
                continue
            line = buffer.decode("ascii", errors="replace").strip()
            buffer.clear()
            if not line:
                continue
            if line == "OK":
                if prompt:
                    raise ModemError("Invite d’envoi SMS absente.")
                return lines
            if line == "ERROR" or line.startswith(("+CME ERROR", "+CMS ERROR")):
                raise ModemError("Commande refusée par le modem.")
            lines.append(line)
        raise ModemError("Délai de réponse du modem dépassé.")

    def _command(self, connection, command: str, **kwargs) -> list[str]:
        connection.write(command.encode("ascii") + b"\r")
        return self._read(connection, **kwargs)

    def probe(self) -> None:
        """Check SMS capabilities without changing PIN or SMS settings."""
        with self._session() as connection:
            modes = response_value(self._command(connection, "AT+CMGF=?"), "+CMGF:")
            if "0" not in modes:
                raise ModemError("Le mode SMS PDU est nécessaire.")
            stores = response_value(self._command(connection, "AT+CPMS=?"), "+CPMS:").split(")", 1)[
                0
            ]
            if f'"{self.storage}"' not in stores:
                raise ModemError("Cette mémoire SMS est indisponible.")

    def _prepare_sms(self, connection) -> None:
        self._command(connection, "AT+CMGF=0")
        self._command(connection, f'AT+CPMS="{self.storage}"')

    @staticmethod
    def _pin(value: str) -> str:
        """Validate before opening the port; a PIN must never form an AT command."""
        if not isinstance(value, str) or not PIN_RE.fullmatch(value):
            raise ValueError("Le PIN doit contenir de 4 à 8 chiffres.")
        return value

    def pin_status(self) -> str:
        """Return the standard +CPIN state without submitting a code."""
        with self._session() as connection:
            return response_value(self._command(connection, "AT+CPIN?"), "+CPIN:")

    def pin_verify(self, current_pin: str) -> None:
        current_pin = self._pin(current_pin)
        with self._session() as connection:
            self._command(connection, f'AT+CPIN="{current_pin}"')

    def pin_enable(self, current_pin: str) -> None:
        current_pin = self._pin(current_pin)
        with self._session() as connection:
            self._command(connection, f'AT+CLCK="SC",1,"{current_pin}"')

    def pin_disable(self, current_pin: str) -> None:
        current_pin = self._pin(current_pin)
        with self._session() as connection:
            self._command(connection, f'AT+CLCK="SC",0,"{current_pin}"')

    def pin_change(self, current_pin: str, new_pin: str) -> None:
        current_pin, new_pin = self._pin(current_pin), self._pin(new_pin)
        with self._session() as connection:
            self._command(connection, f'AT+CPWD="SC","{current_pin}","{new_pin}"')

    def poll(self) -> dict[str, Any]:
        """Read SIM/network status and inbox; never send or delete messages."""
        with self._session() as connection:
            pin = response_value(self._command(connection, "AT+CPIN?"), "+CPIN:")
            result: dict[str, Any] = {
                "sim_status": pin,
                "signal_rssi": None,
                "signal_dbm": None,
                "registration": None,
                "messages": [],
                "storage": self.storage,
            }
            if pin != "READY":
                return result
            signal = response_value(self._command(connection, "AT+CSQ"), "+CSQ:")
            registration = response_value(self._command(connection, "AT+CREG?"), "+CREG:")
            try:
                rssi = int(signal.split(",")[0])
                result["registration"] = int(registration.split(",")[1])
            except (ValueError, IndexError):
                raise ModemError("État réseau non reconnu.") from None
            if 0 <= rssi <= 31:
                result["signal_rssi"] = rssi
                result["signal_dbm"] = -113 + 2 * rssi
            self._prepare_sms(connection)
            result["messages"] = parse_inbox(self._command(connection, "AT+CMGL=4", timeout=30))
            return result

    def send(self, phone_number: str, message: str) -> None:
        """Submit one SMS, without automatic retries or silent multipart charges."""
        if not PHONE_RE.fullmatch(phone_number):
            raise ValueError("Numéro invalide ; utiliser le format +33612345678.")
        if not message or len(message) > 160:
            raise ValueError("Le texte doit contenir entre 1 et 160 caractères.")
        if any(ord(char) > 0xFFFF or 0xD800 <= ord(char) <= 0xDFFF for char in message):
            raise ValueError("Les caractères hors BMP (certains emojis) sont exclus.")
        try:
            pdus = encodeSmsSubmitPdu(phone_number, message, requestStatusReport=False)
        except Exception:
            raise ValueError("Ce texte ne peut pas être encodé en SMS.") from None
        if len(pdus) != 1:
            raise ValueError(
                "Texte trop long pour un SMS : réduire le texte (70 caractères maximum en Unicode)."
            )
        pdu = pdus[0]
        with self._session() as connection:
            pin = response_value(self._command(connection, "AT+CPIN?"), "+CPIN:")
            if pin != "READY":
                raise ModemError("La SIM n’est pas prête.")
            self._command(connection, "AT+CMGF=0")
            try:
                self._command(connection, f"AT+CMGS={pdu.tpduLength}", prompt=True)
                connection.write(str(pdu).encode("ascii") + b"\x1a")
                result = self._read(connection, timeout=60)
                # 3GPP modems normally return a +CMGS message reference before
                # OK. Some firmwares return only OK after accepting the PDU;
                # _read() returns an empty list in that valid case.
                if result:
                    response_value(result, "+CMGS:")
            except (ModemError, serial.SerialException, OSError):
                # A timeout after Ctrl-Z may mean the network accepted the SMS.
                connection.write(b"\x1b")
                raise ModemError(
                    "Envoi refusé ou résultat incertain ; vérifier avant de réessayer."
                ) from None

    def delete(self, message_id: int) -> None:
        """Delete exactly one index in the explicitly configured memory."""
        if isinstance(message_id, bool) or not isinstance(message_id, int):
            raise ValueError("Index SMS invalide.")
        if message_id < 0:
            raise ValueError("Index SMS invalide.")
        with self._session() as connection:
            self._prepare_sms(connection)
            self._command(connection, f"AT+CMGD={message_id},0")
