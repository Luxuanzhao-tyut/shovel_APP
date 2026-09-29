# Python 架构与最小数据链

本版用简单类和函数，未引入服务端、复杂抽象或自写 S7 协议。入口是 examples，不在 import 时启动设备。

读取：load_config + load_variable_map → S7Client → PLCReader → decoder → ShovelState → CSVRecorder。阶段二按有效DB400配置自动计算窗口末端为158，一次批量读到最后REAL；单变量仍读准确的4字节窗口。
写入：具名接口先验证来源/地址，候选与隔离项抛NotImplementedError；已知REAL在dry_run时出计划，关闭dry_run仍被安全链拒绝。所有真实写入都受最低层拒绝约束，没有db_write调用。
规划命令 ShovelCommand 不含 DB/offset，只表达未来目标与限制；速度限制与 Java 设定速度不可未经核验直接对应。

|模块|输入|输出|边界|
|---|---|---|---|
|plc/config.py|YAML 路径|校验后的配置|无 I/O 通信|
|plc/variable_map.py|具名映射|条目或拒绝|UNKNOWN 不得读|
|plc/decoder.py|字节/数值|数值/字节|严格长度、大端、有限写值|
|plc/s7_client.py|连接参数/读窗口|连接状态/字节|单连接、顺序调用、无真实写|
|plc/reader.py|客户端/映射|原始反馈/状态|自动计算bulk窗口，不做单位换算|
|plc/offline_client.py|内存测试字节|只读字节|无connect/写方法，标记offline_fixture|
|plc/writer.py|具名数值|离线计划/拒绝|preview 与执行明确分开|
|plc/safety.py|开关/状态/范围|拒绝理由|未知与调用者伪造状态均不能放行|
|models|具名反馈/目标|数据类|None 表示未知|
|recording/csv_recorder.py|ShovelState|新 CSV|独占创建、逐行 flush|
|trajectory|显式速度点|固定逻辑时刻计划|开环，无执行线程|
|utils/logger.py|日志配置|日志器|新文件，不覆盖|

与 Java 行为区别：Java s7connector 2.1 多连接池及异步脉冲；Python 使用 python-snap7 3.1.2 一个客户端顺序读，不复制异步写、自动心跳和远程切换。两者面向 S7 DB 访问，但协议实现、连接协商和错误行为不同，现场兼容性尚未验证。
不复制Java的155字节整块解析缺陷；阶段二已有Excel业务映射，bulk长度由max_required_end_offset计算。一次S7读减少跨请求偏差，但不能额外保证PLC扫描周期原子性。
来源分层：variable_map只存DB接口；tia_tag_map独立存363个I/Q/M Tag，reader不加载它；signal_chains只作部分关系展示，INFERENCE/POSSIBLE_CANDIDATE不能进入正式I/O。
ShovelState新增斗杆倾角与通讯反馈，其余电压/功率/行走/备用反馈放additional_values，CSV以JSON列保存；未知仍None/errors。
连接配置保留active_ip与两个来源IP，UNRESOLVED_CONFLICT下S7Client在创建库对象前拒绝连接。
采样周期为尽力而为：读取耗时超过周期时下一帧尽快开始，不追赶历史帧；发生通信异常直接退出。没有硬实时保证。

# baseline 对应范围

保留 executeDigTrajectoryPoint 的三轴符号、回转比例和固定时间间隔，输入为显式 TrajectoryPoint。不同于 Java 数据库装载器，不复制疑似反向的 walk/dig 取值；未实现完整模式/闸状态复现，也不自动加载 tag=0 数据。历史 CSV 需由用户明确选择字段和单位后构造点列表。ShovelState 的空示例记录不可当轨迹。
