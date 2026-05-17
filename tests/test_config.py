from mavixdesktop.core.config import Settings


def test_ws_url_from_http():
    s = Settings(signal_url='http://example.com:8000', signal_ws_url='')
    assert s.ws_url == 'ws://example.com:8000/ws/gcs'


def test_ws_url_from_https():
    s = Settings(signal_url='https://example.com', signal_ws_url='')
    assert s.ws_url == 'wss://example.com/ws/gcs'


def test_ws_url_trims_trailing_slash():
    s = Settings(signal_url='http://example.com:8000/', signal_ws_url='')
    assert s.ws_url == 'ws://example.com:8000/ws/gcs'


def test_ws_url_explicit_override():
    s = Settings(
        signal_url='http://nope',
        signal_ws_url='ws://override.example.com/custom',
    )
    assert s.ws_url == 'ws://override.example.com/custom'


def test_http_url_strips_trailing_slash():
    s = Settings(signal_url='http://example.com/')
    assert s.http_url == 'http://example.com'


def test_qgc_explicit_values():
    s = Settings(qgc_host='10.0.0.1', qgc_port=5555, qgc_bind_port=7777)
    assert s.qgc_host == '10.0.0.1'
    assert s.qgc_port == 5555
    assert s.qgc_bind_port == 7777
