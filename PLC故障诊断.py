# -*- coding: utf-8 -*-
"""
露天矿电铲样机 PLC 故障源只读诊断

用途：
- 只读取 PLC，不写任何 DB；
- 直接读取 FC199 汇总到 DB400“电铲故障指示灯”的 7 个源故障位；
- 同时读取 DB402 通讯心跳故障、DB400 通讯/整流/总故障状态。

运行前建议关闭“露天矿电铲样机控制台”，避免两个 Snap7 客户端同时高频访问 PLC。

运行：
    .\.venv\Scripts\python.exe .\PLC故障诊断.py
"""

import time
import sys

PLC_IP = "192.168.2.20"
RACK = 0
SLOT = 1

# 正式 TIA XML：FC199 Read_Data 中“电铲故障指示灯_13”
# = 以下 7 个状态位的 OR。
FAULT_SOURCES = [
    ("整流/ALM",       16, 21, 0, "DB16_ALM_communication.Static_5[8]"),
    ("提升驱动",       11, 101, 0, "DB11_H.Static_6[8]"),
    ("推压驱动",       12, 101, 0, "DB12_C.Static_6[8]"),
    ("回转驱动",       13, 3,   0, "DB13_S.状态字1[8]"),
    ("左行走驱动",     14, 101, 0, "DB14_L_p.Static_6[8]"),
    ("右行走驱动",     15, 101, 0, "DB15_R_p.Static_6[8]"),
    ("开斗/斗门驱动",  17, 101, 0, "DB17_Dipper_communication.Static_6[8]"),
]

def bit(data: bytes, bit_index: int) -> bool:
    return bool(data[0] & (1 << bit_index))

def read_bool(client, db: int, byte_offset: int, bit_offset: int) -> bool:
    return bit(bytes(client.db_read(db, byte_offset, 1)), bit_offset)

def main():
    try:
        import snap7
    except Exception as exc:
        print("无法导入 python-snap7：", exc)
        print(r"请使用工程虚拟环境运行：.\.venv\Scripts\python.exe .\PLC故障诊断.py")
        return 2

    c = snap7.client.Client()
    print(f"连接 PLC：{PLC_IP} / Rack {RACK} / Slot {SLOT}")
    try:
        c.connect(PLC_IP, RACK, SLOT)
        if not c.get_connected():
            print("连接失败：Snap7 未进入 connected 状态。")
            return 3

        print("连接成功。以下全部为只读诊断。\n")
        seen = {name: False for name, *_ in FAULT_SOURCES}

        for sample in range(10):
            # DB400:
            # 0.4 通讯正常，0.6 整流运行，1.4 电铲故障总指示
            comm_ok = read_bool(c, 400, 0, 4)
            rect_on = read_bool(c, 400, 0, 6)
            aggregate_fault = read_bool(c, 400, 1, 4)

            # DB402 第三个 Bool：通讯心跳故障 = DBX0.2
            heartbeat_fault = read_bool(c, 402, 0, 2)

            active = []
            values = []
            for name, db, byte_off, bit_off, symbol in FAULT_SOURCES:
                value = read_bool(c, db, byte_off, bit_off)
                values.append((name, value, db, byte_off, bit_off, symbol))
                seen[name] = seen[name] or value
                if value:
                    active.append(name)

            print(
                f"[{sample+1:02d}/10] "
                f"通讯正常={comm_ok}  "
                f"通讯心跳故障={heartbeat_fault}  "
                f"整流运行={rect_on}  "
                f"总故障={aggregate_fault}"
            )
            print("         故障源：" + ("、".join(active) if active else "无"))
            time.sleep(0.5)

        print("\n========== 10次采样汇总 ==========")
        active_any = [name for name, v in seen.items() if v]
        if active_any:
            print("至少一次为 TRUE 的源故障：", "、".join(active_any))
        else:
            print("7 个源故障位均未检测到 TRUE。")

        print("\n源故障位地址：")
        for name, db, byte_off, bit_off, symbol in FAULT_SOURCES:
            print(f"  {name:<12} DB{db}.DBX{byte_off}.{bit_off}   {symbol}")

        print("\n判断原则：")
        print("1) 如果“总故障=True”，上面的某个源通常应为 True。")
        print("2) DB402 通讯心跳故障与 DB400 总故障是两条不同链路。")
        print("3) 如果只有提升/推压/回转/行走/开斗驱动故障在整流关闭时为 True，")
        print("   可以考虑只在“整流启动”阶段不使用 DB400 总故障作为前置条件；")
        print("   运动命令仍应保留故障联锁。")
        print("4) 如果“整流/ALM”本身为 True，不建议绕过故障强行启动整流。")
        return 0
    except Exception as exc:
        print("\n诊断失败：", repr(exc))
        return 4
    finally:
        try:
            c.disconnect()
        except Exception:
            pass

if __name__ == "__main__":
    sys.exit(main())
