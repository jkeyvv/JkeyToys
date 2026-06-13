"""CRC16-MODBUS 校验计算模块."""


def _build_table() -> list[int]:
    """生成 CRC16-MODBUS 查找表."""
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
        table.append(crc)
    return table


_CRC_TABLE = _build_table()


def crc16_modbus(data: bytes | bytearray) -> int:
    """计算 CRC16-MODBUS 校验值.

    Args:
        data: 待校验的数据

    Returns:
        16 位 CRC 校验值
    """
    crc = 0xFFFF
    for byte in data:
        crc = (crc >> 8) ^ _CRC_TABLE[(crc ^ byte) & 0xFF]
    return crc


def crc16_modbus_bytes(data: bytes | bytearray) -> bytes:
    """计算 CRC16-MODBUS 并返回低字节在前的 2 字节."""
    val = crc16_modbus(data)
    return bytes([val & 0xFF, (val >> 8) & 0xFF])
