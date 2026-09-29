# Excel 上位机点表审计

工程内实际扫描2个xlsx：SOURCE A一份、SOURCE B一份，无工程内同类重复。两份各自与父目录同名文件SHA256完全相同，因此父目录副本也不计作独立证据。没有找到第二份不同文件名的SOURCE A，不虚构重复文件。

|文件|分类|SHA256|父目录同名副本|
|---|---|---|---|
|PLCTags.xlsx|TIA_GLOBAL_TAG_TABLE|d55cb1dfe393e516e8d4cac0242ae3a07e1903a9ca40bcc28d59a14db6fa1ee0|True|
|太理数据对接0612.xlsx|JAVA_MYSQL_POINT_TABLE|3c0bea16c19ac76544ce3782aaf18d554126124e9cae350c3feee0b3a2a14c98|True|

## SOURCE A结构与解释

太理数据对接0612.xlsx：电铲发送41行11列、电铲接收43行11列、Sheet3空表。
左右两组列分别为A:E（序号/点位名称/类型/偏移/备注）及G:K；读取单元格实际偏移，不通过行顺序推算。
电铲发送!A1明确DB400发送、DB401接收，含Excel IP=192.168.0.10、rack0/slot1，并提及MODBUS TCP等方式。
命名source_type=JAVA_MYSQL_POINT_TABLE描述接口层用途，不声称已证明这份xlsx就是MySQL原始导出。

## DB400

提取32 BOOL（18具名+14备用）和38 REAL，总70行。具名56项与Java同DB中文常量逐项匹配。
提升编码器：电铲发送!H38:K38，REAL142，提升向下数值增大。
推压编码器：H39:K39，REAL146，推压向前数值增大。
回转角度：H40:K40，REAL150，铲斗在履带中心向前为0°、右正左负。
斗杆倾角：H41:K41，REAL154，水平0°、下正上负。单位按原文保留，不外推为长度等物理量。
三轴实际转速REAL42/66/90（J13/J19/J25）；电压、电流、功率、转矩、设定转速和左右行走量完整收录。
部分提升电参量单元格明确V/A/kW/Nm/Rpm，其余空备注不自动继承这些单位。

## DB401

提取41 BOOL（30具名+11备用）和6 REAL，共47行。
6个REAL明确：目标6/10/14，速度18/22/26（电铲接收!H3:K8）。目标备注分别关联提升编码器/推压编码器/回转角度，不能当作位置闭环证明。
前24 BOOL（0.0至2.7）形式合法，可记录映射但禁止真实写；通信心跳在D7=0.4，E7记10Hz交替。
第25 BOOL回转向右，D27=2.8非法，INVALID_IN_SOURCE。其后16 BOOL（5具名+11备用）虽然原文字面3.0..4.7可解析，但是否整体错位无独立证明，SOURCE_CONFLICT_OR_INVALID，正式偏移置null。
其中B31“推压/左行自动走执行开始”与Java“推压/左行走自动执行开始”名称不同，只记录候选，不修原表。
INFERENCE ONLY：若原作者意图连续排位，2.7之后应进3.0；但不能据此认定回转向右就应为3.0，更不能自动顺延。

## 连接冲突与协议

Java S7Constant:192.168.2.20；Excel电铲发送!A1:192.168.0.10。rack/slot一致为0/1，IP状态UNRESOLVED_CONFLICT。
active_ip暂保留Java值；连接函数在未人工确认时拒绝，未尝试任何一个IP。来源IP均保留，不选“真实正确值”。
表头的MODBUS TCP提示与Java的S7客户端不是相同证据。本次维持S7 DB路线，不从表头推导Modbus寄存器映射。

## Java批量窗口问题

重新核对S7ReadUtils.readAllData：totalBytes=155，realStart=6，realEnd=155，最后REAL取154..157。Excel明确最后斗杆倾角起点154，需4字节，所以从0读取至少158字节。155字节不足，不再只是代码内部推测，Excel提供了独立的表结构支持。未修改Java。

## 使用边界

DB400可靠地址已可用于代码层只读，全部NOT_TESTED_ON_PLC。DB401所有真实写入仍拒绝，包括6个已知REAL；不启动心跳、远程模式或松闸。
完整117行地址、隔离状态及单元格来源见02_plc_variable_reference.md；原始值另存data/excel_source_audit.json，可与未改动Excel核对。
