# PLC多层信号链

Layer1物理/远程I/O（I/Q/IW/ID）→Layer2内部变量与逻辑（M/MW/MD）→Layer3上位机DB400/DB401→Layer4 Java→Layer5 Python。
这是层次说明，不表示所有箭头已被证明，也不表示Python运行必须经Java转发；Python独立替代通信后端。
来源类型为INFERENCE的关系只用于文档/展示；两端地址分别有Excel证据，箭头需梯形图，NOT_TESTED_ON_PLC。

|链路|两端证据|关系状态|尚缺|
|---|---|---|---|
|提升：%ID46 DWord → PLC internal conversion UNKNOWN → DB400.DBD142 REAL → read_lift_encoder()|PLCTags!PLC Tags A67:E67；太理点表 电铲发送 H38:K38|PARTIALLY_CONFIRMED|类型转换/比例/偏置/标定/单位|
|推压：%ID62 DWord → PLC internal conversion UNKNOWN → DB400.DBD146 REAL → read_push_encoder()|PLC Tags A68:E68；电铲发送 H39:K39|PARTIALLY_CONFIRMED|类型转换/比例/偏置/标定/单位|
|回转：原始源UNKNOWN → DB400.DBD150 REAL → read_swing_angle()|电铲发送 H40:K40；Tag_90仅候选|PARTIALLY_CONFIRMED|原始输入或传感器/交叉引用|

相同中文名不证明同一数据或数值相等。Python业务始终读DB400，不直接读%ID46/%ID62。Tag_90的%ID72不能正式命名为回转角度。

## 未来命令链

Python future command→DB401目标6/10/14、速度18/22/26→PLC internal control UNKNOWN→drive。
Interface exists；PLC internal closed-loop implementation UNKNOWN / NOT YET VERIFIED。关系PARTIALLY_CONFIRMED。
必须进一步核实：目标→比较→速度指令→编码器→减速/停车→执行完成。自动启动后方BOOL受来源错误影响，脉冲/握手不确定。

## 心跳链

DB401.DBX0.4（电铲接收D7/E7明确10Hz交替）→PLC内部通讯监测UNKNOWN→DB400.DBX0.4通讯正常（电铲发送D8）。
关系PARTIALLY_CONFIRMED，未证明中间实现；TIA R_通讯标记%Q462.1也是独立存在的输出，不宣称三个信号等价。不实现启动心跳。

## 模式/安全辅助链

I区远程命令、M区自动开关、Q区模式/闸/零速指示、DB400模式/闸/故障/限位是不同层的候选安全信息。没有梯形图关系就不能把它们组合为可执行联锁。
%IW514/516/518与%MW262/264/260仅名称上可能对应主令汇总，来源关系UNKNOWN，不正式换算或绑定。
