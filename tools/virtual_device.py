"""虚拟下位机 - 用于串口通信测试.

在指定 COM 口上模拟下位机设备，响应上位机的查询命令，并可定时发送上报帧。

使用方法:
    1. 创建一对虚拟串口，例如 COM10 <-> COM11
    2. 上位机连接 COM10，本脚本连接 COM11
    3. 运行: python tools/virtual_device.py COM11 [波特率]
    4. 可选: --report 10   每 10 秒随机发送一条上报帧（默认关闭）

命令响应表:
    0x01 查询版本    -> v1.2.3 (build 4)
    0x02 查询设备信息 -> 设备ID=0x0001, HW=v3, SN=12345678
    0x03 查询温湿度   -> 模拟温湿度 + 状态
    0x04 读取配置     -> 返回指定配置项的值
    0x05 写入配置     -> ACK
    0x10 控制电机     -> 返回结果 + 实际步数
    0x11 GPIO控制    -> 返回执行结果
    0x20 批量读取     -> 返回 8 字节模拟数据
    0xF0 设备复位     -> 返回确认
    0xFF 心跳        -> 返回空数据（ACK）
    0xA0 温度报警    -> 上报（由设备主动发送）
    0xA1 按键事件    -> 上报（由设备主动发送）
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import threading
import time
from pathlib import Path

import serial


# ── 校验算法（与 core/crc.py 一致）──────────────────────────────

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


def xor_checksum(data: bytes) -> bytes:
    result = 0
    for byte in data:
        result ^= byte
    return bytes([result])


# ── 协议编解码 ───────────────────────────────────────────────────

class DeviceProtocol:
    """与上位机协议格式一致的编解码器."""

    def __init__(self, cfg: dict):
        self.header = bytes.fromhex(cfg["header"])
        dummy_str = cfg.get("dummy_byte", "")
        self.dummy_byte = bytes.fromhex(dummy_str) if dummy_str else b""
        self.tail = bytes.fromhex(cfg["tail"])
        self.length_size = cfg["length_size"]
        self.cmd_size = cfg["cmd_size"]
        self.crc_size = cfg["crc_size"]
        self.crc_type = cfg.get("crc_type", "CRC16-MODBUS").upper()
        self.cmd_before_len = cfg.get("cmd_before_len", True)
        self.byte_order = cfg.get("byte_order", "big")

    def _calc_crc(self, data: bytes) -> bytes:
        if self.crc_type == "XOR":
            return xor_checksum(data)
        return crc16_modbus_bytes(data)

    def encode(self, cmd: int, data: bytes = b"") -> bytes:
        cmd_bytes = cmd.to_bytes(self.cmd_size, self.byte_order)
        if self.cmd_before_len:
            length = len(data)
        else:
            length = self.cmd_size + len(data)
        length_bytes = length.to_bytes(self.length_size, self.byte_order)
        payload = cmd_bytes + data
        crc = self._calc_crc(payload) if self.crc_size > 0 else b""
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
        ah = hs + ds  # after header (skip dummy)
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
                if received_crc != self._calc_crc(payload):
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
                if received_crc != self._calc_crc(payload):
                    return None
            cmd = int.from_bytes(payload[:self.cmd_size], self.byte_order)
            data = payload[self.cmd_size:]

        if raw[-ts:] != self.tail:
            return None
        return cmd, data, buf[frame_size:]


# ── 命令响应逻辑 ─────────────────────────────────────────────────

def handle_cmd(cmd: int, data: bytes) -> bytes | None:
    """根据命令号生成响应数据，返回 None 表示不响应."""

    if cmd == 0x01:
        # 查询版本 -> v1.2.3 (build 0x0004)
        return bytes([0x01, 0x02, 0x03, 0x00])

    elif cmd == 0x02:
        # 查询设备信息 -> ID=0x0001, HW=v3, SN=0x12345678
        return (
            bytes([0x00, 0x01])           # 设备ID
            + bytes([0x03])               # 硬件版本 v3
            + bytes([0x12, 0x34, 0x56, 0x78])  # 序列号
        )

    elif cmd == 0x03:
        # 查询温湿度 -> 模拟传感器数据
        sensor_id = data[0] if data else 0x00
        temp = random.randint(200, 350)   # 20.0~35.0°C (×10)
        humi = random.randint(400, 800)   # 40.0~80.0% (×10)
        status = 0x01 if 200 <= temp <= 300 else 0x02  # 正常/偏高
        return (
            temp.to_bytes(2, "big")
            + humi.to_bytes(2, "big")
            + bytes([status])
            + bytes(3)                     # 保留
        )

    elif cmd == 0x04:
        # 读取配置 -> 返回指定配置项的值
        item = data[0] if data else 0x00
        config_db = {
            0x01: bytes([0x00, 0x0A]),    # 采样间隔 = 10
            0x02: bytes([0x01, 0x2C]),    # 上报周期 = 300
            0x03: bytes([0x00, 0x01]),    # 使能标志 = 1
            0x04: bytes([0x00, 0x64]),    # 温度阈值 = 100
        }
        return config_db.get(item, bytes([0xFF, 0xFF]))  # 未知项返回 0xFFFF

    elif cmd == 0x05:
        # 写入配置 -> 返回 0x01 表示成功
        return bytes([0x01])

    elif cmd == 0x10:
        # 控制电机 -> 返回结果 + 实际步数
        if len(data) >= 5:
            direction = data[0]
            speed = int.from_bytes(data[1:3], "big")
            steps = int.from_bytes(data[3:5], "big")
            actual_steps = min(steps, 1000)  # 最大 1000 步
            result = 0x01 if speed <= 5000 else 0x02  # 成功/超速
            return (
                bytes([result])
                + actual_steps.to_bytes(2, "big")
            )
        return bytes([0x00, 0x00, 0x00])  # 参数错误

    elif cmd == 0x11:
        # GPIO控制 -> 返回执行结果
        if len(data) >= 2:
            pin, level = data[0], data[1]
            if pin <= 15 and level in (0, 1):
                return bytes([0x01])  # 成功
        return bytes([0x00])  # 失败

    elif cmd == 0x20:
        # 批量读取 -> 返回 8 字节模拟数据
        if len(data) >= 3:
            addr = int.from_bytes(data[0:2], "big")
            length = data[2]
            # 模拟: 地址递增数据
            return bytes([(addr + i) & 0xFF for i in range(min(length, 8))]).ljust(8, b"\x00")
        return bytes(8)

    elif cmd == 0xF0:
        # 设备复位 -> 返回确认
        return bytes([0x01])

    elif cmd == 0xFF:
        # 心跳 -> ACK (空数据)
        return b""

    else:
        # 未知命令 -> 返回 0x00
        return bytes([0x00])


# ── 上报帧生成 ───────────────────────────────────────────────────

def generate_report(proto: DeviceProtocol) -> bytes | None:
    """随机生成一条上报帧."""
    report_type = random.choice(["temp_alarm", "button_event"])

    if report_type == "temp_alarm":
        # 0xA0 温度报警
        sensor_id = random.randint(0, 3)
        temp = random.randint(300, 400)     # 超阈值温度
        threshold = 300
        alarm_type = random.choice([0x01, 0x02])  # 1=超上限 2=超下限
        data = (
            bytes([sensor_id])
            + temp.to_bytes(2, "big")
            + threshold.to_bytes(2, "big")
            + bytes([alarm_type])
        )
        return proto.encode(0xA0, data)

    elif report_type == "button_event":
        # 0xA1 按键事件
        button_id = random.randint(1, 4)
        action = random.choice([0x01, 0x02, 0x03])  # 1=单击 2=双击 3=长按
        hold_time = random.randint(0, 3000) if action == 0x03 else 0
        data = (
            bytes([button_id])
            + bytes([action])
            + hold_time.to_bytes(2, "big")
        )
        return proto.encode(0xA1, data)

    return None


# ── 上报线程 ─────────────────────────────────────────────────────

def report_loop(ser: serial.Serial, proto: DeviceProtocol, interval: int):
    """定时发送上报帧."""
    while True:
        time.sleep(interval)
        try:
            frame = generate_report(proto)
            if frame:
                ser.write(frame)
                cmd = frame[2]  # CMD 字节
                print(f"[上报] CMD=0x{cmd:02X}  帧={frame.hex(' ').upper()}")
        except Exception:
            break


# ── 主循环 ───────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="虚拟下位机 - 串口通信测试")
    parser.add_argument("port", help="串口号，如 COM11")
    parser.add_argument("baudrate", nargs="?", type=int, default=9600, help="波特率，默认 9600")
    parser.add_argument("--report", type=int, metavar="SEC", help="每 N 秒发送一条随机上报帧")
    args = parser.parse_args()

    # 加载协议配置
    config_dir = Path(__file__).parent.parent / "protocol"
    config_path = config_dir / "protocol.json"
    if not config_path.exists():
        config_path = config_dir / "protocol_default.json"
    with open(config_path, encoding="utf-8") as f:
        proto_cfg = json.load(f)["protocol"]

    proto = DeviceProtocol(proto_cfg)

    ser = serial.Serial(args.port, args.baudrate, timeout=0.1)
    print(f"[虚拟设备] 已打开 {args.port} @ {args.baudrate}")
    print(f"[虚拟设备] 协议: 头={proto_cfg['header']} 尾={proto_cfg['tail']} CRC={proto_cfg['crc_type']}")
    if args.report:
        print(f"[虚拟设备] 上报模式: 每 {args.report} 秒发送一条")
        t = threading.Thread(target=report_loop, args=(ser, proto, args.report), daemon=True)
        t.start()
    print(f"[虚拟设备] 等待上位机命令...\n")

    buf = b""
    try:
        while True:
            chunk = ser.read(256)
            if chunk:
                buf += chunk
                frames, buf = proto.decode(buf)

                for cmd, data in frames:
                    data_hex = data.hex(" ").upper() if data else "(空)"
                    print(f"[RX] CMD=0x{cmd:02X}  DATA=[{data_hex}]")

                    resp_data = handle_cmd(cmd, data)
                    if resp_data is not None:
                        resp_frame = proto.encode(cmd, resp_data)
                        ser.write(resp_frame)
                        resp_hex = resp_data.hex(" ").upper() if resp_data else "(空)"
                        print(f"[TX] CMD=0x{cmd:02X}  DATA=[{resp_hex}]  帧={resp_frame.hex(' ').upper()}")
                    else:
                        print(f"[TX] CMD=0x{cmd:02X}  未响应（未知命令）")
                    print()

    except KeyboardInterrupt:
        print("\n[虚拟设备] 已停止")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
