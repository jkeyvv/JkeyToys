"""自定义帧协议编解码模块.

协议格式（由 ProtocolConfig 定义）:
    cmd_before_len=True:  AA 55 | CMD(1B) | LEN(1B) | DATA... | CRC16(2B) | 0D 0A
    cmd_before_len=False: AA 55 | LEN(1B) | CMD(1B) | DATA... | CRC16(2B) | 0D 0A

    LEN 表示 LEN 字段后到 CRC 前的字节数。
"""

from __future__ import annotations

from dataclasses import dataclass

from core.crc import crc16_modbus_bytes, xor_checksum
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

        # 构建命令字段
        cmd_bytes = cmd.to_bytes(cfg.cmd_size, cfg.byte_order)

        # LEN = LEN 字段后到 CRC 前的字节数
        if cfg.cmd_before_len:
            # 帧头 | CMD | LEN | DATA → LEN = DATA
            length = len(data)
        else:
            # 帧头 | LEN | CMD | DATA → LEN = CMD + DATA
            length = cfg.cmd_size + len(data)

        length_bytes = length.to_bytes(cfg.length_size, cfg.byte_order)

        # CRC（对 CMD + DATA 计算）
        payload = cmd_bytes + data
        crc = self._calc_crc(payload) if cfg.crc_size > 0 else b""

        # 按顺序组装：header + dummy + (CMD+LEN 或 LEN+CMD) + DATA + CRC + tail
        if cfg.cmd_before_len:
            return cfg.header + cfg.dummy_byte + cmd_bytes + length_bytes + data + crc + cfg.tail
        else:
            return cfg.header + cfg.dummy_byte + length_bytes + cmd_bytes + data + crc + cfg.tail

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
        dummy_size = len(cfg.dummy_byte)
        tail_size = len(cfg.tail)
        after_header = header_size + dummy_size  # header + dummy 之后才是 CMD/LEN

        # 查找帧头
        idx = buffer.find(cfg.header)
        if idx == -1:
            return None, b""

        # 丢弃帧头前的垃圾字节
        if idx > 0:
            buffer = buffer[idx:]

        # 最小帧 = 帧头 + dummy + CMD/LEN 字段 + CRC + 帧尾
        min_size = after_header + cfg.cmd_size + cfg.length_size + cfg.crc_size + tail_size
        if len(buffer) < min_size:
            return None, buffer

        if cfg.cmd_before_len:
            # 帧头 | dummy | CMD | LEN | DATA | CRC | 帧尾，LEN = DATA
            cmd = int.from_bytes(buffer[after_header: after_header + cfg.cmd_size], cfg.byte_order)
            length = int.from_bytes(
                buffer[after_header + cfg.cmd_size: after_header + cfg.cmd_size + cfg.length_size],
                cfg.byte_order,
            )
            frame_size = after_header + cfg.cmd_size + cfg.length_size + length + cfg.crc_size + tail_size
            if len(buffer) < frame_size:
                return None, buffer

            raw = buffer[:frame_size]
            data_start = after_header + cfg.cmd_size + cfg.length_size
            data = raw[data_start: data_start + length]

            if cfg.crc_size > 0:
                payload = raw[after_header: after_header + cfg.cmd_size] + data
                received_crc = raw[data_start + length: data_start + length + cfg.crc_size]
                if received_crc != self._calc_crc(payload):
                    return None, buffer[header_size:]
        else:
            # 帧头 | dummy | LEN | CMD | DATA | CRC | 帧尾，LEN = CMD + DATA
            length = int.from_bytes(buffer[after_header: after_header + cfg.length_size], cfg.byte_order)
            frame_size = after_header + cfg.length_size + length + cfg.crc_size + tail_size
            if len(buffer) < frame_size:
                return None, buffer

            raw = buffer[:frame_size]
            payload_start = after_header + cfg.length_size
            payload = raw[payload_start: payload_start + length]

            if cfg.crc_size > 0:
                received_crc = raw[payload_start + length: payload_start + length + cfg.crc_size]
                if received_crc != self._calc_crc(payload):
                    return None, buffer[header_size:]

            cmd = int.from_bytes(payload[: cfg.cmd_size], cfg.byte_order)
            data = payload[cfg.cmd_size:]

        # 帧尾校验
        tail = raw[-tail_size:]
        if tail != cfg.tail:
            return None, buffer[header_size:]

        return Frame(cmd=cmd, data=data, raw=raw), buffer[frame_size:]

    def _calc_crc(self, data: bytes) -> bytes:
        """根据配置计算校验值."""
        crc_type = self._config.crc_type.upper()

        if crc_type == "CRC16-MODBUS":
            return crc16_modbus_bytes(data)
        elif crc_type == "CRC16-CCITT":
            return self._crc16_ccitt_bytes(data)
        elif crc_type == "CRC32":
            return self._crc32_bytes(data)
        elif crc_type == "XOR":
            return xor_checksum(data)
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
