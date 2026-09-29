# 项目当前能力

这是基于原Java电铲后端整理的Python PLC通信基础。架构延续上一阶段：通信、状态模型、CSV、开环速度baseline相互分开，没有重建工程。

现在已从“缺少业务offset”进展到“DB400主要地址有Excel点表依据”，可以准备现场只读验证。**本次没有连接PLC，全部地址尚未现场验证，真实写入仍禁止。**

|反馈|正式接口地址|原表说明|
|---|---|---|
|提升编码器|DB400.DBD142，REAL|提升向下数值增大|
|推压编码器|DB400.DBD146，REAL|推压向前数值增大|
|回转角度|DB400.DBD150，REAL|履带中心向前0°，右正左负|
|斗杆倾角|DB400.DBD154，REAL|水平0°，下正上负|
|提升/推压/回转实际速度|DB400.DBD42 / DBD66 / DBD90|仅保留来源明确的单位，不自动外推|

这四个位置/角度接口均OFFLINE IMPLEMENTED=YES、LIVE PLC VERIFIED=NO。倾角最后占到字节157，批量读取长度由配置自动计算为158，避免Java旧155字节窗口漏读。

# 两类Excel与数据层级

- `太理数据对接0612.xlsx`：上位机通信点表，SOURCE A。DB400共70行（56具名+14备用），DB401共47行。
- `PLCTags.xlsx`：TIA Global Tag Table，SOURCE B，共363个I/Q/M等Tag，独立保存在config/tia_tag_map.yaml。
- 工程内两份不是重复文件；各自与父目录同名文件SHA256相同，因此父目录副本不增加独立证据。

Python正式读DB400、未来写接口对应DB401；**不直接使用%ID46、%ID62或%IW514等内部I/O地址作为正式业务接口**。例如%ID46 DWord与DB400.DBD142 REAL之间可能存在转换，不能凭同名认为数值相等。

每项记录source_type、confidence、verification_status及文件/工作表/单元格/SHA256。CONFIRMED_FROM_EXCEL或VERIFIED_FROM_SOURCE只说明来源证据，不代表现场测试。

# 当前三个重要限制

1. IP冲突：Java=192.168.2.20，Excel=192.168.0.10。active_ip暂保留Java值，状态UNRESOLVED_CONFLICT；连接函数在未人工确认时拒绝，不尝试两个IP。
2. DB401“回转向右”的原始地址2.8非法。未修为3.0；后续16 BOOL（开斗、喇叭、三轴自动开始及11备用）也隔离，正式偏移置null。推压自动开始还有来源名称差异。
3. DB401六个REAL目标6/10/14、速度18/22/26虽已知，仍不能真实写；地址不等于单位、范围、时序或联锁已验证。

# Java与Python的关系

Java仅作为只读审计参考，没有修改、启动或执行其mock。Java mock实际上会写PLC，不能当作离线仿真。Python不修改PLC/TIA/MySQL。没有增加PID、轨迹规划、MPC、ROS2或GUI。

# 架构与数据流

|位置|职责|
|---|---|
|config/plc_config.yaml|连接参数、IP冲突、采样周期、禁写开关|
|config/variable_map.yaml|正式DB点表和隔离的原始错误地址|
|config/tia_tag_map.yaml|独立TIA元数据，不参与业务I/O|
|config/signal_chains.yaml|部分关系展示，不能用作执行路由|
|src/plc|S7连接、编解码、具名reader、写预览、安全拒绝和离线缓冲区|
|src/models|ShovelState、ShovelCommand|
|src/recording|新CSV逐行记录，禁止覆盖历史|
|src/trajectory|旧开环速度复现离线计划|
|examples/tests/docs|学习入口、离线验证、来源审计|

PLC→配置地址→S7Client.read_bytes→PLCReader/decoder→ShovelState→CSV。
单变量读精确窗口；read_all_state按DB一次读完整配置窗口，未知项保留None/errors。其余电参量/行走/备用值在additional_values字典中并记录为JSON列。
Python命令→writer预览→安全拒绝；本版没有真实db_write调用。ShovelCommand不含PLC地址，速度限制与PLC设定值之间的语义尚未核实。

# DB、offset和数据类型

DB是PLC数据块；byte offset从块起点按字节计数。BOOL还需bit offset，只能0～7；2.8是非法位地址，不是可自动进位的小数。
BYTE为8位无符号整数，WORD为16位无符号，INT为16位有符号，DINT为32位有符号，REAL为IEEE754大端float32。名称“编码器”不自带米等单位。
TIA中的%IW/%MW表示16位访问宽度，%ID/%MD表示32位访问宽度；实际类型仍须看Data Type，不直接当作DB偏移。

# 安装与离线运行

推荐Windows 64位Python 3.11，本机测试使用已有Python 3.12.14虚拟环境。python-snap7固定3.1.2，无需额外Snap7 DLL；安装说明见[官方文档](https://python-snap7.readthedocs.io/en/stable/installation.html)。

```powershell
cd 'D:\科研\2026_矿山轨迹规划课题\控制代码'
# 新机器需要创建环境；已有.venv不要重复创建：
# py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe examples/02_read_one_variable.py --offline
.\.venv\Scripts\python.exe examples/03_monitor_plc_state.py --offline --count 3
.\.venv\Scripts\python.exe examples/04_record_plc_to_csv.py --offline --count 3
.\.venv\Scripts\python.exe examples/05_dry_run_write_command.py
.\.venv\Scripts\python.exe examples/06_legacy_trajectory_replay_demo.py
.\.venv\Scripts\python.exe examples/07_show_verified_variable_map.py
.\.venv\Scripts\python.exe examples/08_show_signal_chain.py
```

例02把1234.5写入由配置决定的模拟字节窗口，经PLCReader.read_lift_encoder读取，输出Excel来源和“尚未现场验证”。例03/04的offline分支仍是明确标记offline_empty的空状态，验证输出/记录，不伪造安全状态。
例05显示已知REAL地址和未解锁写入的原因。例06只保留旧速度开环baseline，固定逻辑周期，不真实回放、不自动切模式/松闸。例07展示核心映射及三个警告，例08展示部分链。

# CSV与日志

采样周期在runtime.sample_period_ms，默认100ms。例03/04默认10帧，--count 0持续至Ctrl+C，现场模式不得在本阶段运行。输出新文件保存在data/logs，微秒时间戳且独占创建，不覆盖已有文件；CSV为UTF-8 BOM，UTC时间，None留空。
通信或短读错误终止采样，不沿用旧值；Windows/Python不保证硬实时，单次S7读也不额外承诺PLC扫描周期原子性。

# 下一次现场最小只读验证

由现场人员先确认真实IP。在plc_config中填写已确认的active_ip，保留java_source_ip/excel_source_ip，设置site_ip_confirmed=true、ip_status=CONFIRMED_BY_OPERATOR并填写site_confirmation_note。**本次没有填写或选择真实IP。**
然后运行例01仅连接/断开，再运行例02只读提升编码器，与TIA/原Java显示值核对；由现场人员按既有安全规程小幅操作提升并观察同步变化，再逐步验证推压、回转。第一轮全程不写PLC。

# 如何真正开启写功能

**只有现场允许远程、周围无人、限位与急停正常、PLC工程确认无误且专业人员在场，才可讨论真实控制。**
本版仍无法通过改write_enabled=true/dry_run=false开启真实写。安全链、单位、批准范围、自动启动地址/握手仍未知，safety继续fail closed；不要删除拒绝代码来运行设备。
目标接口存在不代表PLC已具有完整位置闭环。停止接口当前也不能用于实际急停。通信心跳虽有0.4/10Hz来源记录，仍不自动发送。

阅读顺序：[点表审计](docs/07_excel_point_table_audit.md)→[TIA审计](docs/08_tia_plc_tag_table_audit.md)→[信号链](docs/09_plc_signal_chain.md)→[完整变量参考](docs/02_plc_variable_reference.md)→[实施报告](docs/06_implementation_report.md)。
