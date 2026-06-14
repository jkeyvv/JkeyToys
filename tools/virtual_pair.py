"""虚拟串口对 - 无需驱动，用 TCP Socket 桥接两个串口角色.

原理:
    本脚本同时扮演「虚拟下位机」和「TCP 服务端」。
    上位机通过 com2tcp 工具（或任意虚拟串口映射工具）连接到本脚本的 TCP 端口。
    也可以直接用 loop:// 做单进程自测。

简单用法（单进程自测，不依赖外部工具）:
    python tools/virtual_pair.py --self-test

这会启动一个线程模拟上位机，另一线程模拟下位机，通过内存管道通信。
"""

from __future__ import annotations

import argparse
import json
import random
import socket
import threading
import time
from pathlib import Path

# ── CRC16-MODBUS ─────────────────────────────────────────────────

def _build_crc_table() -> list[int]:
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

_CRC_TABLE = _build_crc_table()

def crc16_modbus_bytes(data: bytes) -> bytes:
    crc = 0xFFFF
    for byte in data:
        crc = (crc >> 8) ^ _CRC_TABLE[(crc ^ byte) & 0xFF]
    return bytes([crc & 0xFF, (crc >> 8) & 0xFF])


# ── 协议编解码 ───────────────────────────────────────────────────

class Protocol:
    def __init__(self, cfg: dict):
        self.header = bytes.fromhex(cfg["header"])
        dummy_str = cfg.get("dummy_byte", "")
        self.dummy_byte = bytes.fromhex(dummy_str) if dummy_str else b""
        self.tail = bytes.fromhex(cfg["tail"])
        self.length_size = cfg["length_size"]
        self.cmd_size = cfg["cmd_size"]
        self.crc_size = cfg["crc_size"]
        self.cmd_before_len = cfg.get("cmd_before_len", True)
        self.byte_order = cfg.get("byte_order", "big")

    def encode(self, cmd: int, data: bytes = b"") -> bytes:
        cmd_bytes = cmd.to_bytes(self.cmd_size, self.byte_order)
        if self.cmd_before_len:
            length = len(data)
        else:
            length = self.cmd_size + len(data)
        length_bytes = length.to_bytes(self.length_size, self.byte_order)
        payload = cmd_bytes + data
        crc = crc16_modbus_bytes(payload) if self.crc_size > 0 else b""
        if self.cmd_before_len:
            return self.header + self.dummy_byte + cmd_bytes + length_bytes + data + crc + self.tail
        else:
            return self.header + self.dummy_byte + length_bytes + cmd_bytes + data + crc + self.tail

    def decode(self, buffer: bytes) -> tuple[list[tuple[int, bytes]], bytes]:
        frames = []
        remaining = buffer
        while True:
            result = self._parse_one(remaining)
            if result is None:
                break
            cmd, data, remaining = result
            frames.append((cmd, data))
        return frames, remaining

    def _parse_one(self, buf: bytes) -> tuple[int, bytes, bytes] | None:
        idx = buf.find(self.header)
        if idx == -1:
            return None
        if idx > 0:
            buf = buf[idx:]
        hs = len(self.header)
        ds = len(self.dummy_byte)
        ts = len(self.tail)
        ah = hs + ds
        min_size = ah + self.cmd_size + self.length_size + self.crc_size + ts
        if len(buf) < min_size:
            return None
        if self.cmd_before_len:
            cmd = int.from_bytes(buf[ah:ah + self.cmd_size], self.byte_order)
            length = int.from_bytes(buf[ah + self.cmd_size:ah + self.cmd_size + self.length_size], self.byte_order)
            frame_size = ah + self.cmd_size + self.length_size + length + self.crc_size + ts
            if len(buf) < frame_size:
                return None
            raw = buf[:frame_size]
            data_start = ah + self.cmd_size + self.length_size
            data = raw[data_start:data_start + length]
            if self.crc_size > 0:
                payload = raw[ah:ah + self.cmd_size] + data
                received_crc = raw[data_start + length:data_start + length + self.crc_size]
                if received_crc != crc16_modbus_bytes(payload):
                    return None
        else:
            length = int.from_bytes(buf[ah:ah + self.length_size], self.byte_order)
            frame_size = ah + self.length_size + length + self.crc_size + ts
            if len(buf) < frame_size:
                return None
            raw = buf[:frame_size]
            payload_start = ah + self.length_size
            payload = raw[payload_start:payload_start + length]
            if self.crc_size > 0:
                received_crc = raw[payload_start + length:payload_start + length + self.crc_size]
                if received_crc != crc16_modbus_bytes(payload):
                    return None
            cmd = int.from_bytes(payload[:self.cmd_size], self.byte_order)
            data = payload[self.cmd_size:]
        if raw[-ts:] != self.tail:
            return None
        return cmd, data, buf[frame_size:]


# ── 虚拟设备响应 ─────────────────────────────────────────────────

def handle_cmd(cmd: int, data: bytes) -> bytes | None:
    if cmd == 0x01:
        return bytes([0x01, 0x02, 0x03, 0x00])
    elif cmd == 0x02:
        return bytes([0x00, 0x01, 0x03, 0x12, 0x34, 0x56, 0x78])
    elif cmd == 0x03:
        temp = random.randint(200, 350)
        humi = random.randint(400, 800)
        return temp.to_bytes(2, "big") + humi.to_bytes(2, "big") + bytes([0x01, 0, 0, 0])
    elif cmd == 0x04:
        item = data[0] if data else 0
        db = {0x01: b'\x00\x0A', 0x02: b'\x01\x2C', 0x03: b'\x00\x01', 0x04: b'\x00\x64'}
        return db.get(item, b'\xFF\xFF')
    elif cmd == 0x05:
        return bytes([0x01])
    elif cmd == 0x10:
        if len(data) >= 5:
            steps = int.from_bytes(data[3:5], "big")
            return bytes([0x01]) + min(steps, 1000).to_bytes(2, "big")
        return bytes([0x00, 0x00, 0x00])
    elif cmd == 0x11:
        return bytes([0x01]) if len(data) >= 2 and data[0] <= 15 else bytes([0x00])
    elif cmd == 0x20:
        if len(data) >= 3:
            addr = int.from_bytes(data[0:2], "big")
            ln = data[2]
            return bytes([(addr + i) & 0xFF for i in range(min(ln, 8))]).ljust(8, b"\x00")
        return bytes(8)
    elif cmd == 0xF0:
        return bytes([0x01])
    elif cmd == 0xFF:
        return b""
    return bytes([0x00])


# ── 内存管道（替代真实串口）────────────────────────────────────────

class Pipe:
    """线程安全的字节管道，模拟串口的双向通信."""

    def __init__(self):
        self._buf = b""
        self._lock = threading.Lock()
        self._cond = threading.Condition()

    def write(self, data: bytes):
        with self._cond:
            self._buf += data
            self._cond.notify_all()

    def read(self, size: int = 256, timeout: float = 0.5) -> bytes:
        with self._cond:
            if not self._buf:
                self._cond.wait(timeout=timeout)
            chunk = self._buf[:size]
            self._buf = self._buf[size:]
        return chunk


# ── 自测：模拟上位机 ─────────────────────────────────────────────

def client_thread(proto: Protocol, pipe_to_device: Pipe, pipe_from_device: Pipe):
    """模拟上位机，发送命令并接收响应."""
    import sys

    commands = [
        (0x01, b"",           "查询版本"),
        (0x02, b"",           "查询设备信息"),
        (0x03, bytes([0x01]), "查询温湿度"),
        (0x04, bytes([0x01]), "读取配置"),
        (0x05, bytes([0x01, 0x00, 0x0A]), "写入配置"),
        (0x10, bytes([0x01, 0x00, 0x64, 0x00, 0x0A]), "控制电机"),
        (0x11, bytes([0x03, 0x01]), "GPIO控制"),
        (0x20, bytes([0x00, 0x10, 0x08]), "批量读取"),
        (0xF0, b"",           "设备复位"),
        (0xFF, b"",           "心跳"),
    ]

    buf = b""
    passed = 0
    failed = 0
    time.sleep(0.5)  # 等待设备端就绪

    for cmd, data, name in commands:
        # 发送
        frame = proto.encode(cmd, data)
        pipe_to_device.write(frame)
        data_hex = data.hex(" ").upper() if data else "-"
        print(f"[上位机 TX] {name:<12} CMD=0x{cmd:02X}  DATA=[{data_hex}]  帧={frame.hex(' ').upper()}")

        # 等待响应
        deadline = time.time() + 3.0
        while time.time() < deadline:
            chunk = pipe_from_device.read(256)
            if chunk:
                buf += chunk
                frames, buf = proto.decode(buf)
                if frames:
                    resp_cmd, resp_data = frames[0]
                    resp_hex = resp_data.hex(" ").upper() if resp_data else "-"
                    ok = resp_cmd == cmd
                    if ok:
                        passed += 1
                    else:
                        failed += 1
                    print(f"[上位机 RX] {name:<12} CMD=0x{resp_cmd:02X}  DATA=[{resp_hex}]  {'PASS' if ok else 'FAIL'}")
                    break
        else:
            failed += 1
            print(f"[上位机 RX] {name:<12} TIMEOUT")

    print(f"\n{'='*50}")
    print(f"测试结果: {passed} PASS / {failed} FAIL / {len(commands)} 总计")


# ── 自测：模拟下位机 ─────────────────────────────────────────────

def device_thread(proto: Protocol, pipe_from_client: Pipe, pipe_to_client: Pipe):
    """模拟下位机，接收命令并发送响应."""
    buf = b""
    while True:
        chunk = pipe_from_client.read(256, timeout=2.0)
        if chunk:
            buf += chunk
            frames, buf = proto.decode(buf)
            for cmd, data in frames:
                data_hex = data.hex(" ").upper() if data else "-"
                print(f"[下位机 RX] CMD=0x{cmd:02X}  DATA=[{data_hex}]")

                resp_data = handle_cmd(cmd, data)
                if resp_data is not None:
                    resp_frame = proto.encode(cmd, resp_data)
                    pipe_to_client.write(resp_frame)
                    resp_hex = resp_data.hex(" ").upper() if resp_data else "-"
                    print(f"[下位机 TX] CMD=0x{cmd:02X}  DATA=[{resp_hex}]")


# ── 主入口 ───────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="虚拟串口对 - 通信自测")
    parser.add_argument("--self-test", action="store_true", help="单进程自测（不依赖外部工具）")
    parser.add_argument("--port", type=int, default=5555, help="TCP 端口（用于 com2tcp 模式）")
    args = parser.parse_args()

    config_dir = Path(__file__).parent.parent / "protocol"
    config_path = config_dir / "protocol.json"
    if not config_path.exists():
        config_path = config_dir / "protocol_default.json"
    with open(config_path, encoding="utf-8") as f:
        cfg = json.load(f)

    proto = Protocol(cfg["protocol"])

    if args.self_test:
        print("=" * 50)
        print("  虚拟串口自测 - 上位机 <-> 下位机")
        print("=" * 50)
        print()

        # 创建双向管道
        pipe_c2d = Pipe()  # client -> device
        pipe_d2c = Pipe()  # device -> client

        # 启动设备线程
        t = threading.Thread(target=device_thread, args=(proto, pipe_c2d, pipe_d2c), daemon=True)
        t.start()

        # 在主线程运行上位机测试
        client_thread(proto, pipe_c2d, pipe_d2c)
        return

    # TCP 模式（配合 com2tcp 使用）
    print(f"[虚拟设备] TCP 服务端启动在 127.0.0.1:{args.port}")
    print(f"[虚拟设备] 用 com2tcp 将虚拟串口映射到此端口即可")

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", args.port))
    server.listen(1)

    while True:
        conn, addr = server.accept()
        print(f"[虚拟设备] 连接来自 {addr}")
        buf = b""
        try:
            while True:
                chunk = conn.recv(256)
                if not chunk:
                    break
                buf += chunk
                frames, buf = proto.decode(buf)
                for cmd, data in frames:
                    resp = handle_cmd(cmd, data)
                    if resp is not None:
                        conn.sendall(proto.encode(cmd, resp))
        except ConnectionResetError:
            pass
        finally:
            conn.close()
            print("[虚拟设备] 连接断开")


if __name__ == "__main__":
    main()
