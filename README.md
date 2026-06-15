# JkeyToys v1.0.1

基于 PySide6 的 UART 上位机调试工具，支持自定义帧协议通信和原始数据打印。

## 功能

- **串口管理** — 自动扫描可用串口，配置波特率/数据位/停止位/校验位
- **数据收发** — HEX / ASCII 双模式切换，原始字节收发
- **协议通信** — 自定义帧协议自动封装/解析，CRC16-MODBUS 校验
- **原始数据打印** — 深色终端风格，RX/TX 彩色区分，带时间戳
- **协议帧高亮** — 解析成功的协议帧以橙色高亮显示

## 协议格式

默认帧格式（可通过「协议 → 协议配置」自定义）：

```
帧头(4B) + 命令(2B) + 长度(2B) + 数据(NB) + 校验(1B) + 帧尾(4B)
AA555AA5    CMD        LEN       DATA...     XOR       0D0AA55A
```

| 字段   | 字节数 | 说明                                  |
| ------ | ------ | ------------------------------------- |
| 帧头   | 4      | 固定 `0xAA 0x55 0x5A 0xA5`            |
| 命令   | 2      | 命令字节                              |
| 长度   | 2      | LEN 后到校验前的字节数（即 DATA 长度） |
| 数据   | N      | 可变长度载荷                          |
| 校验   | 1      | 对命令+数据做 XOR 校验                |
| 帧尾   | 4      | 固定 `0x0D 0x0A 0xA5 0x5A`            |

可配置项：CMD 位置（LEN 前/后）、校验算法（XOR / CRC16-MODBUS / CRC16-CCITT / CRC32 / 无）、Dummy 字节（帧头后插入的忽略字节）、字节序（大端/小端）。

## 项目结构

```
JkeyToys/
├── main.py                  # 入口
├── requirements.txt         # Python 依赖
├── protocol/                # 协议配置
│   ├── protocol.json        # 用户协议配置（运行时生成）
│   └── protocol_default.json  # 出厂默认协议模板
├── core/                    # 后端（零 UI 依赖）
│   ├── crc.py               # CRC 校验算法
│   ├── protocol_config.py   # 协议帧格式配置（ProtocolConfig 数据类）
│   ├── protocol.py          # 帧协议编解码（Protocol 类）
│   └── serial_worker.py     # 串口收发 QThread
├── ui/                      # 界面
│   ├── main_window.py       # 主窗口
│   ├── serial_panel.py      # 串口配置面板
│   ├── data_panel.py        # 数据收发面板
│   ├── protocol_panel.py    # 命令调试面板
│   ├── protocol_editor.py   # 命令清单编辑器
│   └── protocol_settings_dialog.py  # 协议配置对话框
└── tools/                   # 测试与模拟工具
    ├── virtual_device.py    # 虚拟下位机（模拟设备响应 + 定时上报）
    ├── virtual_pair.py      # 内存管道自测
    └── test_serial.py       # 端到端串口通信测试
```

## 快速开始

```bash
pip install -r requirements.txt
python main.py
```

## 使用说明

1. 左侧面板选择串口、设置波特率等参数，点击 **打开串口**
2. 右侧接收区实时显示收到的原始数据
3. 发送区输入数据，选择 HEX 或 ASCII 模式，点击 **发送**
4. 勾选 **协议封装** 可自动按帧格式打包发送（需填写命令字节）
5. 接收到的数据会自动尝试协议解析，解析成功的帧以橙色高亮显示

## 测试工具

### 虚拟下位机

无需实体硬件，用虚拟串口对模拟下位机设备：

```bash
# 启动虚拟设备（基本模式 — 仅响应查询命令）
python tools/virtual_device.py COM3 115200

# 带定时上报 — 每 5 秒随机发送温度报警或按键事件
python tools/virtual_device.py COM3 115200 --report 5
```

上位机连接配对的另一个串口（如 COM2）即可通信。

支持的命令：查询版本(0x01)、查询设备信息(0x02)、查询温湿度(0x03)、读取配置(0x04)、写入配置(0x05)、控制电机(0x10)、GPIO控制(0x11)、批量读取(0x20)、设备复位(0xF0)、心跳(0xFF)。

上报帧：温度报警(0xA0)、按键事件(0xA1)。

### 内存管道自测

单进程自测，不依赖串口驱动：

```bash
python tools/virtual_pair.py --self-test
```

### 端到端串口测试

需要一对已配对的虚拟串口（如 ELTIMA VSPD 创建的 COM2/COM3）：

```bash
python tools/test_serial.py
```

测试内容：CRC 类型、帧格式、10 条命令收发、粘包、半包、CRC 错误帧丢弃、快速连续发送等。

## 依赖

- Python >= 3.10
- PySide6 >= 6.5.0
- pyserial >= 3.5
