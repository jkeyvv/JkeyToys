"""协议帧格式配置模块."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ProtocolConfig:
    """协议帧格式配置.

    定义帧头、帧尾、各字段大小和 CRC 算法。
    LEN 始终包含 DATA，length_includes_cmd 控制 LEN 是否包含 CMD。
    byte_order 控制多字节字段的字节序（big=大端, little=小端）。
    """

    header: bytes = b"\xAA\x55"            # 帧头
    tail: bytes = b"\x0D\x0A"              # 帧尾
    length_size: int = 1                   # 长度字段字节数
    cmd_size: int = 1                      # 命令字段字节数
    crc_size: int = 2                      # CRC 字段字节数（0 = 无 CRC）
    crc_type: str = "CRC16-MODBUS"         # CRC 算法类型
    length_includes_cmd: bool = True       # LEN 是否包含 CMD（始终包含 DATA）
    byte_order: str = "big"                # 字节序：big=大端, little=小端
    query_timeout_ms: int = 3000           # 查询超时时间（毫秒）

    def to_dict(self) -> dict:
        """序列化为字典."""
        return {
            "header": self.header.hex().upper(),
            "tail": self.tail.hex().upper(),
            "length_size": self.length_size,
            "cmd_size": self.cmd_size,
            "crc_size": self.crc_size,
            "crc_type": self.crc_type,
            "length_includes_cmd": self.length_includes_cmd,
            "byte_order": self.byte_order,
            "query_timeout_ms": self.query_timeout_ms,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ProtocolConfig:
        """从字典反序列化."""
        return cls(
            header=bytes.fromhex(data["header"]),
            tail=bytes.fromhex(data["tail"]),
            length_size=data.get("length_size", 1),
            cmd_size=data.get("cmd_size", 1),
            crc_size=data.get("crc_size", 2),
            crc_type=data.get("crc_type", "CRC16-MODBUS"),
            length_includes_cmd=data.get("length_includes_cmd", True),
            byte_order=data.get("byte_order", "big"),
            query_timeout_ms=data.get("query_timeout_ms", 3000),
        )

    @staticmethod
    def hex_to_bytes(hex_str: str) -> bytes:
        """HEX 字符串转 bytes，支持空格分隔和 0x 前缀."""
        clean = hex_str.replace(" ", "").replace("0x", "").replace("0X", "")
        return bytes.fromhex(clean)


# 默认配置
DEFAULT_CONFIG = ProtocolConfig()
