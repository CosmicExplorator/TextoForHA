"""Exercise the serial protocol without a real modem or SMS recipient."""

import importlib.util
from collections import deque
from pathlib import Path

import pytest
from gsmmodem.pdu import decodeSmsPdu

MODULE = Path(__file__).parents[1] / "dongle_link/app/drivers/at_modem.py"
spec = importlib.util.spec_from_file_location("qualcomm_modem_test", MODULE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
ATModem, ModemError = module.ATModem, module.ModemError
# SMS-DELIVER: 2026-10-01 12:00:00 UTC; GSM7 "hellohello".
DELIVER = "00040B919761556443F60000620110210000000AE8329BFD4697D9EC37"


class FakeSerial:
    """Respond on writes, never accidentally acknowledge a later command."""

    def __init__(self, responses):
        self.responses = deque(responses)
        self.buffer = bytearray()
        self.writes = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def reset_input_buffer(self):
        self.buffer.clear()

    def write(self, value):
        self.writes.append(value)
        if value in (b"\x1b\r", b"\x1b"):
            return
        expected, response = self.responses.popleft()
        if expected is not None:
            assert value == expected
        self.buffer.extend(response)

    def read(self, count=1):
        result = self.buffer[:count]
        del self.buffer[:count]
        return bytes(result)


def connect(monkeypatch, responses):
    connection = FakeSerial(responses)

    def factory(port, baudrate, **kwargs):
        assert port == "/dev/serial/by-id/test-modem"
        assert kwargs["exclusive"] is True
        return connection

    monkeypatch.setattr(module.serial, "Serial", factory)
    return ATModem("/dev/serial/by-id/test-modem"), connection


def ok(command, payload=""):
    return command.encode() + b"\r", (payload + "\r\nOK\r\n").encode()


def test_probe_checks_read_storage(monkeypatch):
    modem, connection = connect(
        monkeypatch,
        [
            ok("AT"),
            ok("AT+CMGF=?", "+CMGF: (0-1)"),
            ok("AT+CPMS=?", '+CPMS: ("ME","MT","SM"),("SM"),("SM")'),
        ],
    )
    modem.probe()
    assert connection.closed
    assert not connection.responses
    assert b"AT+CMGF=0\r" not in connection.writes


def test_probe_rejects_unsupported_read_storage(monkeypatch):
    modem, _ = connect(
        monkeypatch,
        [
            ok("AT"),
            ok("AT+CMGF=?", "+CMGF: (0,1)"),
            ok("AT+CPMS=?", '+CPMS: ("ME"),("SM"),("SM")'),
        ],
    )
    with pytest.raises(ModemError, match="mémoire"):
        modem.probe()


def test_poll_reads_status_and_sms_without_sending_or_deleting(monkeypatch):
    modem, connection = connect(
        monkeypatch,
        [
            ok("AT"),
            ok("AT+CPIN?", "+CPIN: READY"),
            ok("AT+CSQ", "+CSQ: 31,99"),
            ok("AT+CREG?", "+CREG: 0,1"),
            ok("AT+CMGF=0"),
            ok('AT+CPMS="SM"', "+CPMS: 1,20,1,20,1,20"),
            ok("AT+CMGL=4", f"+CMGL: 7,0,,26\r\n{DELIVER}"),
        ],
    )
    result = modem.poll()
    assert result["signal_dbm"] == -51
    assert result["registration"] == 1
    assert result["messages"][0]["content"] == "hellohello"
    assert result["messages"][0]["id"] == "7"
    assert result["messages"][0]["unread"] is True
    assert not any(b"CMGS" in w or b"CMGD" in w for w in connection.writes)


def test_locked_sim_never_submits_pin(monkeypatch):
    modem, connection = connect(
        monkeypatch,
        [
            ok("AT"),
            ok("AT+CPIN?", "+CPIN: SIM PIN"),
        ],
    )
    result = modem.poll()
    assert result["sim_status"] == "SIM PIN"
    assert result["messages"] == []
    assert not any(b"CPIN=" in w for w in connection.writes)


def test_unknown_signal(monkeypatch):
    modem, _ = connect(
        monkeypatch,
        [
            ok("AT"),
            ok("AT+CPIN?", "+CPIN: READY"),
            ok("AT+CSQ", "+CSQ: 99,99"),
            ok("AT+CREG?", "+CREG: 0,5"),
            ok("AT+CMGF=0"),
            ok('AT+CPMS="SM"'),
            ok("AT+CMGL=4"),
        ],
    )
    assert modem.poll()["signal_dbm"] is None


@pytest.mark.parametrize("text", ["Bonjour éè à €", "你好", "AT+CMGD=1\r\nOK"])
def test_send_encodes_pdu_and_waits_for_confirmation(monkeypatch, text):
    modem, connection = connect(
        monkeypatch,
        [
            ok("AT"),
            ok("AT+CPIN?", "+CPIN: READY"),
            ok("AT+CMGF=0"),
            (None, b"\r\n> "),
            (None, b"\r\n+CMGS: 9\r\nOK\r\n"),
        ],
    )
    modem.send("+33612345678", text)
    assert connection.writes[-1].endswith(b"\x1a")
    decoded = decodeSmsPdu(connection.writes[-1][:-1].decode())
    assert decoded["text"] == text
    assert decoded["number"] == "+33612345678"
    assert connection.closed


@pytest.mark.parametrize(
    "number,text",
    [
        ('+33612345678"\rAT+CMGD=1', "hello"),
        ("abc", "hello"),
        ("+33612345678", ""),
        ("+33612345678", "a" * 161),
        ("+33612345678", "你" * 71),
        ("+33612345678", "😀"),
    ],
)
def test_invalid_send_never_opens_port(monkeypatch, number, text):
    def unexpected_open(*args, **kwargs):
        pytest.fail("Validation must happen before opening a device")

    monkeypatch.setattr(module.serial, "Serial", unexpected_open)
    with pytest.raises(ValueError):
        ATModem("unused").send(number, text)


def test_uncertain_send_is_never_retried(monkeypatch):
    modem, connection = connect(
        monkeypatch,
        [
            ok("AT"),
            ok("AT+CPIN?", "+CPIN: READY"),
            ok("AT+CMGF=0"),
            (None, b"\r\n> "),
            (None, b"\r\n+CMS ERROR: 500\r\n"),
        ],
    )
    with pytest.raises(ModemError, match="incertain"):
        modem.send("+33612345678", "test")
    assert sum(w.endswith(b"\x1a") for w in connection.writes) == 1
    assert connection.closed


def test_delete_targets_one_index_in_selected_storage(monkeypatch):
    modem, connection = connect(
        monkeypatch,
        [
            ok("AT"),
            ok("AT+CMGF=0"),
            ok('AT+CPMS="SM"'),
            ok("AT+CMGD=7,0"),
        ],
    )
    modem.delete(7)
    assert connection.writes[-1] == b"AT+CMGD=7,0\r"


@pytest.mark.parametrize("index", [-1, True, "1\rAT+CMGD=0,4"])
def test_delete_rejects_invalid_indices(index):
    with pytest.raises(ValueError):
        ATModem("unused").delete(index)


def test_interleaved_urc_and_invalid_records():
    messages = module.parse_inbox(
        [
            '+CMTI: "SM",7',
            "+CMGL: 7,1,,26",
            "+CREG: 1",
            DELIVER,
        ]
    )
    assert len(messages) == 1
    assert messages[0]["unread"] is False
    with pytest.raises(ModemError, match="incomplète"):
        module.parse_inbox(["+CMGL: 7,1,,26"])
    with pytest.raises(ModemError, match="décodé"):
        module.parse_inbox(["+CMGL: 7,1,,26", "00"])


def test_timeout_is_bounded(monkeypatch):
    tick = iter([0, 0, 1, 2, 9])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(tick))
    with pytest.raises(ModemError, match="Délai"):
        ATModem("unused")._read(FakeSerial([]), timeout=8)


def test_serial_error_hides_details(monkeypatch):
    def fail(*args, **kwargs):
        raise module.serial.SerialException("private data")

    monkeypatch.setattr(module.serial, "Serial", fail)
    with pytest.raises(ModemError, match="occupé") as err:
        ATModem("unused").probe()
    assert "private" not in str(err.value)


@pytest.mark.parametrize(
    "payload,expected",
    [
        ("04D83DDE00", "😀"),
        ("02D83D", "\ufffd"),
        ("04004100E9", "Aé"),
    ],
)
def test_received_unicode_is_safe_for_home_assistant_json(payload, expected):
    pdu = "00040B919761556443F6000862011021000000" + payload
    messages = module.parse_inbox(["+CMGL: 1,0,,26", pdu])
    assert messages[0]["content"] == expected
    # Strict UTF-8 encoding is required by HA's JSON encoder.
    messages[0]["content"].encode("utf-8")
