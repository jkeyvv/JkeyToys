"""协议帧格式配置模块."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ProtocolConfig:
    """协议帧格式配置.

    定义帧头、帧尾、各字段大小和 CRC 算法。
    LEN 表示 LEN 字段后到 CRC 前的字节数。
    cmd_before_len 控制 CMD 在 LEN 前还是后。
    byte_order 控制多字节字段的字节序（big=大端, little=小端）。
    """

    header: bytes = b"\xAA\x55\x5A\xA5"    # 帧头
    dummy_byte: bytes = b""                # 帧头后的 Dummy 字节（空=无）
    tail: bytes = b"\x0D\x0A\xA5\x5A"     # 帧尾
    length_size: int = 2                   # 长度字段字节数
    cmd_size: int = 2                      # 命令字段字节数
    crc_size: int = 1                      # CRC 字段字节数（0 = 无 CRC）
    crc_type: str = "XOR"                  # CRC 算法类型
    cmd_before_len: bool = True            # True=帧头+CMD+LEN+DATA, False=帧头+LEN+CMD+DATA
    byte_order: str = "little"             # 字节序：big=大端, little=小端
    query_timeout_ms: int = 3000           # 查询超时时间（毫秒）

    def to_dict(self) -> dict:
        """序列化为字典."""
        return {
            "header": self.header.hex().upper(),
            "dummy_byte": self.dummy_byte.hex().upper() if self.dummy_byte else "",
            "tail": self.tail.hex().upper(),
            "length_size": self.length_size,
            "cmd_size": self.cmd_size,
            "crc_size": self.crc_size,
            "crc_type": self.crc_type,
            "cmd_before_len": self.cmd_before_len,
            "byte_order": self.byte_order,
            "query_timeout_ms": self.query_timeout_ms,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ProtocolConfig:
        """从字典反序列化."""
        dummy_str = data.get("dummy_byte", "")
        return cls(
            header=bytes.fromhex(data["header"]),
            dummy_byte=bytes.fromhex(dummy_str) if dummy_str else b"",
            tail=bytes.fromhex(data["tail"]),
            length_size=data.get("length_size", 2),
            cmd_size=data.get("cmd_size", 2),
            crc_size=data.get("crc_size", 1),
            crc_type=data.get("crc_type", "XOR"),
            cmd_before_len=data.get("cmd_before_len", True),
            byte_order=data.get("byte_order", "little"),
            query_timeout_ms=data.get("query_timeout_ms", 3000),
        )

    @staticmethod
    def hex_to_bytes(hex_str: str) -> bytes:
        """HEX 字符串转 bytes，支持空格分隔和 0x 前缀."""
        clean = hex_str.replace(" ", "").replace("0x", "").replace("0X", "")
        return bytes.fromhex(clean)


# 默认配置
DEFAULT_CONFIG = ProtocolConfig()
