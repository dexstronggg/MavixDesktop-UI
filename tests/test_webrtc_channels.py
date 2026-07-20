from __future__ import annotations

import json
from unittest.mock import MagicMock

from mavixdesktop.webrtc.channels import (
    ConfigChannel,
    DataChannelHub,
    PacketChannel,
    PingChannel,
)


def _mock_channel(label: str, ready_state: str = 'connecting') -> MagicMock:
    ch = MagicMock()
    ch.label = label
    ch.readyState = ready_state
    ch._handlers = {}

    def fake_on(event: str, handler=None):
        if handler is not None:
            ch._handlers[event] = handler
            return handler
        def _register(fn):
            ch._handlers[event] = fn
            return fn
        return _register

    ch.on.side_effect = fake_on
    ch.send = MagicMock()
    return ch


def _fire(ch: MagicMock, event: str, *args) -> None:
    handler = ch._handlers.get(event)
    if handler is None:
        return
    handler(*args)


def test_packet_send_when_closed_is_noop():
    ch = _mock_channel('packet-channel', ready_state='connecting')
    pc = PacketChannel(ch)
    pc.send_bytes(b'\xAA')
    ch.send.assert_not_called()


def test_packet_send_when_open():
    ch = _mock_channel('packet-channel', ready_state='open')
    pc = PacketChannel(ch)
    pc.send_bytes(b'\xAA\xBB')
    ch.send.assert_called_once_with(b'\xAA\xBB')


def test_packet_send_swallows_errors():
    ch = _mock_channel('packet-channel', ready_state='open')
    ch.send.side_effect = RuntimeError('boom')
    pc = PacketChannel(ch)
    pc.send_bytes(b'X')


def test_packet_on_message_dispatches_to_handler():
    ch = _mock_channel('packet-channel')
    pc = PacketChannel(ch)
    received: list[bytes] = []
    pc.on_packet = received.append
    _fire(ch, 'message', b'\x01\x02\x03')
    assert received == [b'\x01\x02\x03']


def test_packet_on_message_no_handler():
    ch = _mock_channel('packet-channel')
    PacketChannel(ch)
    _fire(ch, 'message', b'\x01')


def test_packet_ignores_non_bytes_messages():
    ch = _mock_channel('packet-channel')
    pc = PacketChannel(ch)
    received: list = []
    pc.on_packet = received.append
    _fire(ch, 'message', 'a string')
    assert received == []


def test_packet_handler_errors_swallowed():
    ch = _mock_channel('packet-channel')
    pc = PacketChannel(ch)
    pc.on_packet = lambda _: (_ for _ in ()).throw(RuntimeError('cb'))
    _fire(ch, 'message', b'\x00')


def test_ping_send_when_closed_is_noop():
    ch = _mock_channel('ping-channel')
    pc = PingChannel(ch)
    pc.send_ping()
    ch.send.assert_not_called()


def test_ping_send_records_inflight():
    ch = _mock_channel('ping-channel', ready_state='open')
    pc = PingChannel(ch)
    pc.send_ping()
    ch.send.assert_called_once()
    sent_payload = ch.send.call_args.args[0]
    assert isinstance(sent_payload, (bytes, bytearray))
    assert len(sent_payload) == PingChannel._PAYLOAD_SIZE
    assert pc.last_rtt_ms is None


def test_ping_echo_records_rtt():
    ch = _mock_channel('ping-channel', ready_state='open')
    pc = PingChannel(ch)
    pc.send_ping()
    echoed = ch.send.call_args.args[0]
    _fire(ch, 'message', bytes(echoed))
    assert pc.last_rtt_ms is not None
    assert pc.last_rtt_ms >= 0


def test_ping_ignores_wrong_size_payload():
    ch = _mock_channel('ping-channel', ready_state='open')
    pc = PingChannel(ch)
    _fire(ch, 'message', b'\x00\x01\x02')
    assert pc.last_rtt_ms is None


def test_config_send_when_closed_is_noop():
    ch = _mock_channel('config-channel')
    cc = ConfigChannel(ch)
    cc.send_json({'type': 'reboot'})
    ch.send.assert_not_called()


def test_config_send_when_open_emits_utf8():
    ch = _mock_channel('config-channel', ready_state='open')
    cc = ConfigChannel(ch)
    cc.send_json({'a': 1})
    args = ch.send.call_args.args[0]
    assert json.loads(args.decode('utf-8')) == {'a': 1}


def test_config_send_unencodable_does_not_raise():
    ch = _mock_channel('config-channel', ready_state='open')
    cc = ConfigChannel(ch)

    class Bad: ...

    cc.send_json({'x': Bad()})


def test_config_on_message_decodes_json_bytes():
    ch = _mock_channel('config-channel')
    cc = ConfigChannel(ch)
    received: list = []
    cc.on_message = received.append
    _fire(ch, 'message', json.dumps({'type': 'fc', 'kind': 'mavlink'}).encode('utf-8'))
    assert received == [{'type': 'fc', 'kind': 'mavlink'}]


def test_config_on_message_decodes_json_str():
    ch = _mock_channel('config-channel')
    cc = ConfigChannel(ch)
    received: list = []
    cc.on_message = received.append
    _fire(ch, 'message', json.dumps([1, 2, 3]))
    assert received == [[1, 2, 3]]


def test_config_on_open_callback_fires():
    ch = _mock_channel('config-channel')
    cc = ConfigChannel(ch)
    fired = []
    cc.on_opened = lambda: fired.append(True)
    _fire(ch, 'open')
    assert fired == [True]


def test_config_on_message_skips_invalid_json():
    ch = _mock_channel('config-channel')
    cc = ConfigChannel(ch)
    received: list = []
    cc.on_message = received.append
    _fire(ch, 'message', b'not-json{{')
    assert received == []


def test_hub_attach_packet():
    hub = DataChannelHub()
    ch = _mock_channel('packet-channel')
    assert hub.attach(ch) is True
    assert isinstance(hub.packet, PacketChannel)
    assert hub.ping is None
    assert hub.config is None


def test_hub_attach_ping():
    hub = DataChannelHub()
    assert hub.attach(_mock_channel('ping-channel')) is True
    assert isinstance(hub.ping, PingChannel)


def test_hub_attach_config():
    hub = DataChannelHub()
    assert hub.attach(_mock_channel('config-channel')) is True
    assert isinstance(hub.config, ConfigChannel)


def test_hub_attach_unknown_label():
    hub = DataChannelHub()
    assert hub.attach(_mock_channel('weather-forecast')) is False
    assert hub.packet is None and hub.ping is None and hub.config is None


def test_hub_close_clears_all():
    hub = DataChannelHub()
    hub.attach(_mock_channel('packet-channel'))
    hub.attach(_mock_channel('ping-channel'))
    hub.attach(_mock_channel('config-channel'))
    hub.close()
    assert hub.packet is None
    assert hub.ping is None
    assert hub.config is None
