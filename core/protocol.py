"""自定义帧协议编解码模块.

协议格式:
    帧头 + 长度 + 命令 + 数据 + CRC + 帧尾

    各字段大小和内容由 ProtocolConfig 定义，默认:
    AA 55 | LEN(1B) | CMD(1B) | DATA... | CRC16(2B) | 0D 0A

    长度字段 = CMD + DATA（默认），可通过 length_includes_* 配置
"""

from __future__ import annotations

from dataclasses import dataclass

from core.crc import crc16_modbus_bytes
from core.protocol_config import ProtocolConfig, DEFAULT_CONFIG


@dataclass
class Frame:
    """解析后的数据帧."""

    cmd: int
    data: bytes
    raw: bytes  # 原始完整帧字节

    @property
    def data_hex(self) -> str:
        return self.data.hex(" ").upper()

    @property
    def raw_hex(self) -> str:
        return self.raw.hex(" ").upper()

    def __repr__(self) -> str:
        return f"Frame(cmd=0x{self.cmd:02X}, data=[{self.data_hex}], len={len(self.data)})"


class Protocol:
    """协议编解码器.

    Args:
        config: 协议帧格式配置，默认使用 DEFAULT_CONFIG
    """

    def __init__(self, config: ProtocolConfig | None = None):
        self._config = config or DEFAULT_CONFIG

    @property
    def config(self) -> ProtocolConfig:
        return self._config

    def encode(self, cmd: int, data: bytes = b"") -> bytes:
        """编码一帧数据.

        Args:
            cmd: 命令字节 (0x00-0xFF)
            data: 数据载荷

        Returns:
            完整帧字节序列
        """
        cfg = self._config

        # 计算长度字段值（LEN 始终包含 DATA，可选包含 CMD）
        length = len(data)
        if cfg.length_includes_cmd:
            length += cfg.cmd_size

        # 构建长度字段
        length_bytes = length.to_bytes(cfg.length_size, cfg.byte_order)

        # 构建命令字段
        cmd_bytes = cmd.to_bytes(cfg.cmd_size, cfg.byte_order)

        # 组装 payload = LEN + CMD + DATA
        payload = length_bytes + cmd_bytes + data

        # CRC
        if cfg.crc_size > 0:
            crc = self._calc_crc(payload)
        else:
            crc = b""

        return cfg.header + payload + crc + cfg.tail

    def decode(self, buffer: bytes) -> tuple[list[Frame], bytes]:
        """从缓冲区中解析所有完整帧.

        Args:
            buffer: 累积的原始字节缓冲区

        Returns:
            (解析出的帧列表, 剩余未解析的字节)
        """
        frames: list[Frame] = []
        remaining = buffer

        while True:
            frame, remaining = self._parse_one(remaining)
            if frame is None:
                break
            frames.append(frame)

        return frames, remaining

    def _parse_one(self, buffer: bytes) -> tuple[Frame | None, bytes]:
        """尝试从缓冲区头部解析一帧.

        Returns:
            (Frame 或 None, 剩余字节)
        """
        cfg = self._config
        header_size = len(cfg.header)
        tail_size = len(cfg.tail)

        # 查找帧头
        idx = buffer.find(cfg.header)
        if idx == -1:
            return None, b""

        # 丢弃帧头前的垃圾字节
        if idx > 0:
            buffer = buffer[idx:]

        # 最小帧 = 帧头 + 长度字段 + CRC + 帧尾
        min_size = header_size + cfg.length_size + cfg.crc_size + tail_size
        if len(buffer) < min_size:
            return None, buffer

        # 解析长度字段
        length = int.from_bytes(buffer[header_size: header_size + cfg.length_size], cfg.byte_order)

        # 完整帧大小 = 帧头 + 长度字段 + length(=CMD+DATA) + CRC + 帧尾
        frame_size = header_size + cfg.length_size + length + cfg.crc_size + tail_size
        if len(buffer) < frame_size:
            return None, buffer

        # 提取完整帧
        raw = buffer[:frame_size]
        payload_start = header_size + cfg.length_size
        payload = raw[payload_start: payload_start + length]

        # CRC 校验
        if cfg.crc_size > 0:
            received_crc = raw[payload_start + length: payload_start + length + cfg.crc_size]
            expected_crc = self._calc_crc(payload)
            if received_crc != expected_crc:
                return None, buffer[header_size:]
        else:
            received_crc = b""

        # 帧尾校验
        tail = raw[-tail_size:]
        if tail != cfg.tail:
            return None, buffer[header_size:]

        # 从 payload 中解析 CMD 和 DATA
        cmd = int.from_bytes(payload[: cfg.cmd_size], cfg.byte_order)
        data = payload[cfg.cmd_size:]

        return Frame(cmd=cmd, data=data, raw=raw), buffer[frame_size:]

    def _calc_crc(self, data: bytes) -> bytes:
        """根据配置计算 CRC."""
        crc_type = self._config.crc_type.upper()

        if crc_type == "CRC16-MODBUS":
            return crc16_modbus_bytes(data)
        elif crc_type == "CRC16-CCITT":
            return self._crc16_ccitt_bytes(data)
        elif crc_type == "CRC32":
            return self._crc32_bytes(data)
        else:
            # 默认使用 CRC16-MODBUS
            return crc16_modbus_bytes(data)

    @staticmethod
    def _crc16_ccitt_bytes(data: bytes) -> bytes:
        """CRC16-CCITT 计算."""
        crc = 0xFFFF
        for byte in data:
            crc ^= byte << 8
            for _ in range(8):
                if crc & 0x8000:
                    crc = (crc << 1) ^ 0x1021
                else:
                    crc <<= 1
                crc &= 0xFFFF
        return bytes([crc & 0xFF, (crc >> 8) & 0xFF])

    @staticmethod
    def _crc32_bytes(data: bytes) -> bytes:
        """CRC32 计算."""
        import zlib
        crc = zlib.crc32(data) & 0xFFFFFFFF
        return crc.to_bytes(4, "little")

    def find_frames_in_stream(self, buffer: bytes) -> tuple[list[Frame], bytes]:
        """与 decode 相同，提供更直观的名称."""
        return self.decode(buffer)


# 默认协议实例（向后兼容）
DEFAULT_PROTOCOL = Protocol()
