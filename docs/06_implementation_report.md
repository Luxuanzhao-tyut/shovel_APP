# 阶段二实施报告：地址补全、来源分层与只读升级

维护目录：D:\科研\2026_矿山轨迹规划课题\控制代码。沿用阶段一架构增量修改，未重建工程。上一阶段67项测试，本阶段99项通过。本次没有连接现场PLC，没有执行任何真实PLC写入。

## A. Excel数据源

工程内发现2份Excel，按内容识别：

|文件|分类|内容|
|---|---|---|
|太理数据对接0612.xlsx|SOURCE A / JAVA_MYSQL_POINT_TABLE|电铲发送、接收两个左右分栏点表，另有空Sheet3|
|PLCTags.xlsx|SOURCE B / TIA_GLOBAL_TAG_TABLE|PLC Tags、TagTable Properties|

工程内两份不是同源重复；两份分别与父目录同名文件SHA256完全相同，父目录副本不计作额外证据。没有发现工程内第二份不同文件名的点表，不虚构“两份独立确认”。完整指纹、原始行和单元格见data/excel_source_audit.json、docs/07_excel_point_table_audit.md。
来源分类JAVA_MYSQL_POINT_TABLE表示接口层用途，不宣称已证明xlsx就是MySQL原始导出。

## B. DB400

70个地址条目：56具名反馈、14备用；32 BOOL和38 REAL。全部有Excel依据，CONFIRMED_FROM_EXCEL / NOT_TESTED_ON_PLC。

|具名反馈|类型|byte offset|原文方向|
|---|---|---|---|
|提升编码器|REAL|142|提升向下数值增大|
|推压编码器|REAL|146|推压向前数值增大|
|回转角度|REAL|150|履带中心向前0°，右正左负|
|斗杆倾角|REAL|154|水平0°，下正上负|
|提升实际转速|REAL|42|原备注Rpm|
|推压实际转速|REAL|66|原备注为空，不继承其他行单位|
|回转实际转速|REAL|90|原备注为空，不继承其他行单位|

电压、电流、功率、转矩、设定速度、左右行走、模式、通讯、故障、限位、执行结果完整收录。其余反馈在ShovelState.additional_values中保留，CSV以JSON列记录。
bulk长度按有效地址自动算出158字节，覆盖0..157。再次核对Java S7ReadUtils.java:84仍为totalBytes=155，最后REAL154..157不足；Excel斗杆倾角地址支持这一缺陷判断，未修改Java。

## C. DB401

原表47行：41 BOOL与6 REAL。6 REAL确认如下，全部仍禁止真实发送：

|命令|byte offset|
|---|---|
|提升/右行走目标位置|6|
|推压/左行走目标位置|10|
|回转目标位置|14|
|提升/右行走设定转速|18|
|推压/左行走设定转速|22|
|回转设定转速|26|

前24 BOOL（0.0..2.7）地址可记录。第25项回转向右=2.8非法，标INVALID_IN_SOURCE，正式byte/bit=null，保留raw_source_address。
后续16 BOOL（开斗、喇叭、三轴自动开始、11备用）缺独立证据确认是否整体错位，SOURCE_CONFLICT_OR_INVALID并隔离。未修2.8为3.0，也未顺延任何来源地址。
推压自动开始原文“推压/左行自动走执行开始”与Java名称不同，仅候选关联，不把名称改成已确认事实。
通信心跳0.4和10Hz交替备注已记录，无自动心跳实现或启动副作用。

## D. PLC IP与协议

Java=192.168.2.20；Excel历史记录=192.168.0.10；rack=0、slot=1一致。2026-09-24已确认现场样机PLC IP=192.168.2.20，ip_status=SITE_CONFIRMED。
active_ip暂保留Java值，两个原始IP均保留，不选择“真实正确IP”。site_ip_confirmed=false，连接在创建S7库对象前拒绝，不尝试任一地址。
Excel表头提到MODBUS TCP等方式，Java实际使用S7；此差异已记录，本阶段不切换协议或推导Modbus寄存器。

## E. TIA PLC Tags

363个Tag独立保存于config/tia_tag_map.yaml。分组：DI31、AI3、DO14、远程_I32、远程_Q19、默认变量表259、Modbus_TCP5。

|信号|原始类型|Logical Address|
|---|---|---|
|提升编码器|DWord|%ID46|
|推压编码器|DWord|%ID62|
|R_推压主令|Int|%IW514|
|R_回转主令|Int|%IW516|
|R_提升主令|Word|%IW518|
|m提升主令汇总|Int|%MW260|
|m推压主令汇总|Int|%MW262|
|m回转主令|Int|%MW264|

模式：样机本地/远程%I3.4/.5；远程本地/远程操作%I510.7/%I511.0；挖掘/行走输入%I511.2/.3；Dig_mode/Propel_mode输出%Q1.1/.2。
内部：远程操作%M100.3，自动挖掘%M100.6，自动提升推压开关%M210.4，自动行走开关%M100.5。
松/抱闸：提升推压%M110.0/.1，行走%M110.2/.3，回转%M110.4/.5。
远程状态：挖掘/行走%Q460.6/.7；推压/提升/回转松闸%Q461.0/.1/.2；提升/推压/回转零速%Q461.3/.4/.5；通讯标记%Q462.1。
Tag_90 Real %ID72只证明该Tag存在，解释为回转角度仅POSSIBLE_CANDIDATE。完整363行附录见08文档。

## F. 信号链

- 提升：%ID46 DWord → PLC internal conversion UNKNOWN → DB400.DBD142 REAL → read_lift_encoder()。
- 推压：%ID62 DWord → PLC internal conversion UNKNOWN → DB400.DBD146 REAL → read_push_encoder()。
- 回转：原始来源UNKNOWN → DB400.DBD150 REAL → read_swing_angle()。

以上PARTIALLY_CONFIRMED仅表示两端证据可见，未证明中间箭头，不能假设数值相等。TIA不覆盖DB接口。
未来命令：Python→DB401目标/速度→PLC internal control UNKNOWN→drive。Interface exists，内部闭环NOT YET VERIFIED。
心跳→内部监测→通讯正常也仅部分确认，不执行任何新增控制逻辑。见09文档及仅供展示的signal_chains.yaml。

## G. Python增量更新

|类别|修改或新增|
|---|---|
|config|更新plc_config.yaml、variable_map.yaml；新增tia_tag_map.yaml、signal_chains.yaml|
|src/plc|variable_map.py增加来源/等级/合法位/隔离校验及窗口计算；reader.py增加倾角、按DB批量读；config.py与s7_client.py保留并阻止未解决IP冲突；writer.py预览带完整来源；新增offline_client.py|
|src/models|shovel_state.py增加斗杆倾角、通讯状态、additional_values|
|recording|csv_recorder.py将additional_values保存为JSON列|
|examples|更新02为具名reader离线测试；新增07映射与警告、08信号链；03/04空状态和05/06离线逻辑沿用|
|tests|更新test_variable_map.py、test_safety.py、test_client.py、test_examples.py；保留decoder与CSV/baseline验证|
|tools/data|新增只读audit_excel_sources.py及excel_source_audit.json来源记录|
|docs|更新README、01/02/03/04/05/06；新增07/08/09；更新pytest_result.txt|

没有修改decoder、ShovelCommand、安全拒绝模块或旧速度baseline算法。没有新增正式I/Q/M通信路径，没有自写协议/PID。35个Python文件均有中文模块说明并通过语法检查。正式运行无需新增Excel依赖；审计提取使用内置openpyxl环境。

## H. 测试与离线示例

Windows x64，Python3.12.14，pytest8.4.2，python-snap73.1.2。`python -m pytest`：**99 passed in 12.20s**。
覆盖四个位置REAL独立向量、三轴速度、bulk158/短读拒绝、BOOL0..7/2.8隔离、已知REAL禁写、IP冲突、TIA隔离、候选禁止、生命周期与离线禁止网络。

|实际运行|结果|
|---|---|
|02 --offline|成功，经过PLCReader读取1234.5，并打印Excel来源及尚未现场验证|
|03 --offline --count 3|成功，3帧offline_empty，未知没有变成正常值|
|04 --offline --count 3|成功，3行新CSV，不覆盖旧文件|
|05|成功，DB401 offset18的5.0计划，written=false|
|06|成功，3帧旧开环速度逻辑计划，无真实调度|
|07|成功，核心映射及IP冲突/2.8非法/持续禁写三个警告|
|08|成功，三条部分信号链展示|
|01|仅测试--help，未运行真实连接|

新CSV：data/plc_record_20260912_235106_073714.csv；此前plc_record_20260912_214314_152466.csv仍存在。七份对应日志在logs。沙箱限制日志创建后，经执行权限审查运行相同离线命令成功；未连接PLC。

## I. 当前能力

|接口|OFFLINE IMPLEMENTED|LIVE PLC VERIFIED|
|---|---|---|
|提升编码器|YES|NO|
|推压编码器|YES|NO|
|回转角度|YES|NO|
|斗杆倾角|YES|NO|
|DB400批量状态|YES|NO|

代码层地址、类型与读取路径已完成，不声称设备在线值或单位标定已验证。

## J. 真实写入与最终审计

**REAL PLC WRITE ENABLED = NO**。
write_enabled=false、dry_run=true；即使改变为true/false，安全链未知仍拒绝，底层无真实db_write/write_area调用。
Java128文件数量及SHA256均一致；两份Excel指纹均未变。未修改PLC/TIA工程。
有效bit_offset>7：0；有效POSSIBLE_CANDIDATE：0；正式映射中TIA地址：0；bulk末端158；IP仍UNRESOLVED_CONFLICT。
Git仍返回not a git repository，未修复、初始化或提交父目录遗留.git。

## K. 下一次现场最小验证

1. 人工确认PLC实际IP，记录依据；保留两个来源IP，再填写active_ip、site_ip_confirmed、ip_status、site_confirmation_note。
2. 例01只连接/断开。
3. 例02只读DB400.DBD142，与TIA/原Java显示值交叉验证。
4. 由现场人员按既有安全规程轻微操作提升，观察Python变化和方向。
5. 成功后依次只读DB400.DBD146、DB400.DBD150。

现场第一阶段不写PLC，不自动发送心跳，不自动切远程/松闸。

## L. 仍待确认

实际IP；DB401 2.8正确地址及后续BOOL是否整体错位；回转原始源；%ID46→DB400.DBD142与%ID62→DB400.DBD146的转换；编码器物理单位；三轴设定速度真实单位/比例；目标单位；PLC内部闭环逻辑；启动脉冲/握手；执行结果含义；完整安全联锁、新鲜度与现场批准范围。
推压自动启动名称差异、表头MODBUS提示与实际S7部署的关系亦保留待核。源码与Excel证据优先于推测，不为可运行而修复来源。
