from mavixdesktop.speedtester.units import Size, SizeType, Standard


def test_decimal_kb_is_125_bytes():
    s = Size(1, SizeType.KB, Standard.Decimal)
    assert s.get(SizeType.Byte) == 125


def test_binary_kb_is_1024_bytes():
    s = Size(1, SizeType.KB, Standard.Binary)
    assert s.get(SizeType.Byte) == 1024


def test_decimal_mb_is_125_kbytes():
    s = Size(1, SizeType.MB, Standard.Decimal)
    assert s.get(SizeType.Byte) == 125_000


def test_binary_mb_is_1mib():
    s = Size(1, SizeType.MB, Standard.Binary)
    assert s.get(SizeType.Byte) == 1_048_576


def test_bytes_to_mb_binary():
    s = Size(1_048_576, SizeType.Byte)
    assert s.get(SizeType.MB, Standard.Binary) == 1


def test_bytes_to_mb_decimal():
    s = Size(125_000, SizeType.Byte)
    assert s.get(SizeType.MB, Standard.Decimal) == 1


def test_round_trip_kb_to_kb():
    s = Size(7, SizeType.KB, Standard.Binary)
    assert s.get(SizeType.KB, Standard.Binary) == 7


def test_cross_standard_conversion():
    """1 KB decimal (125 B) → KB binary should be 125/1024 ≈ 0.122."""
    s = Size(1, SizeType.KB, Standard.Decimal)
    assert abs(s.get(SizeType.KB, Standard.Binary) - 125 / 1024) < 1e-9


def test_negative_value_preserved():
    """Speeds start at -1 to signal 'no measurement yet'."""
    s = Size(-1, SizeType.Byte)
    assert s.get(SizeType.MB, Standard.Binary) < 0
