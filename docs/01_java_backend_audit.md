# 阶段二补充：Excel交叉审计

原Java保持只读。新增点表支持DB400的56个具名反馈和14备用地址；DB401的6个REAL及前24 BOOL地址可据来源记录，非法2.8与后续16 BOOL隔离。当前正式表以02_plc_variable_reference.md为准；本文末尾旧表保留为阶段一“地址尚缺”时的审计记录，不用于运行。
Excel电铲发送!A1给出192.168.0.10，Java仍为192.168.2.20，UNRESOLVED_CONFLICT；不得静默覆盖。表头提及MODBUS TCP，不改变Java实际S7协议路线。
Excel电铲发送!J41明确斗杆倾角REAL起点154，占154/155/156/157四字节。从0读取至少158字节；重新检查Java readAllData仍为totalBytes=155。因此原155-byte窗口不足已受到点表进一步支持，Java未修改。
全部来源地址NOT_TESTED_ON_PLC；TIA的%ID46/%ID62与DB400 REAL只确认两端，转换未验证。

# 1. Java 工程整体作用

审计对象：`../plc_backend/plc_backend`（相对新工程根目录）。2026-09-12 静态审计，不启动 Java、不连接 PLC/MySQL。源码哈希见 java_source_hashes.json。
Spring Boot 2.6.13 / Java 8，REST 电机操作、Netty WebSocket 状态广播、MyBatis/MySQL 状态与参数记录，以及历史速度回放。摄像头部分不迁移。

# 2. PLC 通信架构

`S7Constant.java:5-15` 确认 IP=192.168.2.20、rack=0、slot=1；DB400 为电铲→上位机，DB401 为上位机→电铲。源码未发现 DB404 或 16384 的有效映射依据。
`pom.xml` 使用 com.github.s7connector:s7connector:2.1；连接池默认 5 个，读写各有专用高频连接。application.yml 数据库为 localhost/dcc，HTTP 5556、WebSocket 8081 /ws。数据库凭据不复制。

# 3. Java 中读取 PLC 的流程

单点：中文 NameConstant → PlcDataMetaCache → MySQL 两张元数据表的 byte_offset/bit_offset → S7ReadUtils.readBool/readReal → Java Boolean/Float。
批量：readAllData 从 DB400 offset 0 读 155 字节；前三字节解析 24 位后删 6 位（18 BOOL）；offset 6 开始每 4 字节取 REAL，最后起点 154，会要求读至 157。Arrays.copyOfRange 会补零，最后 REAL 不是完整 PLC 反馈。
MotorStatusServiceImpl 将这些值按数据库返回的 var_name 顺序反射赋到 DTO。元数据 SELECT 无 ORDER BY；不能据 Java 字段声明顺序推导地址。
@Scheduled(fixedRate=100) 获取状态、广播 JSON；当前动作另读编码器及执行结果，但 result 局部变量未形成完整到位判据。

# 4. Java 中写 PLC 的流程

MotorController → 各机构 Service / ButtonService → ValueUtils / S7WriteUtils → DB401。REAL 使用 ByteBuffer 默认大端 float32；BOOL 先读整字节再改位、写回、回读核对。普通操作按请求触发，无统一固定周期；高频接口标注 10 Hz，轨迹默认 100 ms；异步按钮置 true 后 2000 ms 清 false。
底层没有统一远程/故障/限位/数值安全检查。读改写并非 PLC 原子位写；多连接可丢失相邻位更新。回读一致不能证明动作成功。

# 5. PLC 变量表

完整当前变量表见 `02_plc_variable_reference.md`。阶段一仅凭Java时，所有具名业务地址均UNKNOWN_FROM_DATABASE；阶段二已由Excel补齐可靠部分。本文历史附录保留当时状态，不能当作当前配置。正式条目包含来源单元格、SHA256、置信度与现场验证状态。

# 6. 提升控制链

LifterRightMoveServiceImpl：手动用实际速度+输入增量；负增量对应向上、正对应向下；零时速度及两方向清零。目标模式读取提升编码器比较目标，写目标/速度/方向；源码夹限位置 1000..10000、速度 -100..100，但注释称暂定，不能视为现场批准范围。挖掘模式判断被注释；读取松闸/限位指示不等于写入前拦截。

# 7. 推压控制链

PushLeftMoveServiceImpl：手动实际速度+增量，正前进、负后退；目标模式编码器比较后写方向、目标、速度。位置夹限 1000..30000、速度 -100..100。模式检查被注释，无完整安全闭锁。

# 8. 回转控制链

RotationServiceImpl：手动正向右、负向左；疑似错误地在 DB400 读取 ROTATION_SET_SPEED（其常量属于 DB401）。目标角以 (target+360)%360 处理后写目标与方向，比较方向发生在归一化之前。类注释声称闭环不是 PLC 梯形图证据；负大角度及跨零方向需要核实。

# 9. 行走控制链

WalkServiceImpl：提升/右行走与推压/左行走复用速度、方向、目标和闸信号。模式判断被注释。整体前后将 leftActualSpeed 加给 LIFT_RIGHT_SET_SPEED、rightActualSpeed 加给 PUSH_LEFT_SET_SPEED，左右疑似交换；单侧转弯与目标模式另有路径。位置反馈未知的 TODO 仍存在。

# 10. 数据记录流程

MotorStatusServiceImpl → MotorStatusDTO → BeanUtils → ShovelStatus（BOOL）、ShovelParams（Float）两表；录制默认 false，TagManager 分配 tag，batch_id 为 yyyyMMddHHmmssSSS 文本。两次 insert 未显示同一事务保障，可能形成不完整配对。类内直接调用 @Async 方法可能绕过 Spring 代理，需运行期确认。HistoryDataPlayBackServiceImpl 是历史展示链，与 PLC 速度回放需区分。

# 11. 当前历史轨迹复现方法

TrajectoryExecutor.loadTrajectory 查询 tag=0，按 batch_id 排序并关联状态表；timeMs 为格式化日期数字而非标准 epoch 毫秒。walk 分支却取提升/推压/回转实际速度，其他分支取右/左行走实际速度，存在模式命名与取值反向疑点。
scheduleAtFixedRate 默认 100 ms，逐点写速度/方向，不使用误差修正，也未按采样时间差调度。因此是 **速度序列开环回放 / open-loop speed replay**：人工示教→实际速度记录→固定周期重发。
挖掘路径提升负上正下、推压正前负后；回转负右正左，实际写值 -rotationSpeed/13.2，与手动回转符号需对照。完整路径自动远程、闸变化脉冲；挖掘回转首次切换还会抱提升/推压闸。Python 仅保留速度计划 baseline，禁止复制这些自动动作。

# 12. Java 工程中已经存在的闭环/目标位置相关能力

CONFIRMED：三个目标位置 REAL 的调用、三个自动启动 BOOL 脉冲接口（ButtonServiceImpl）、三个执行结果 BOOL 的读取，以及编码器/角度 REAL 读取接口存在。
LIKELY：这些名称可能对应 PLC 位置控制与完成反馈。
阶段二已补充可靠地址与原表方向注释；仍UNKNOWN：未给出的单位、比例、使能时序、脉冲宽度适配、PLC内部闭环及到位条件；DB401后段BOOL地址仍隔离。不得实现自造PID或宣称已有可靠位置闭环。

# 13. Java 工程中发现的可疑点

- 155 字节窗口最后 REAL 越界补零；元数据无序导致反射顺序不稳定。
- 两个 DB 共用按中文名称索引的 Map，同名可相互覆盖；没有地址空值检查。
- ValueUtils.writeUpDownLeftRightAtomic 实际逐条写且总返回 true，忽略写入结果，无原子性。
- S7WriteUtils 捕获异常返回 null；ButtonService 的 thenApply 忽略 false 也声称成功。
- 手动非零方向分支未统一清除反向位；增量速度缺统一夹限。
- 模式判断被注释，远程/故障/限位检查未集中，抱闸状态通过 !release 推导，缺独立反馈证明。
- 异步脉冲复位失败、并发同字节写、回放中止与在途命令竞态需要验证。
- TrajectoryExecutor.mock 名为仿真却调用真实写入，不能运行；safeStopAllMotors 只是速度归零和方向位清零，不是硬件急停。
- tag=0 固定筛选、模式取值反向、回转比例、格式化日期当 timeMs、执行结果未用作轨迹误差反馈均需确认。
- 回放自然结束调用 stopCurrentExecutionAsync 只清理调度资源，未见在该路径调用 safeStopAllMotors；若末帧非零，不能保证设备停止。safeExecutePlcOperation 吞异常且写调用返回值被忽略，后续帧可能继续。

以上只记录，不改动原 Java 或 PLC 工程。

## 历史附录：阶段一PLC变量表（当前映射见02文档）

|中文名称|Java 常量名|PLC DB|类型|byte offset|bit offset|读/写|物理含义|当前是否确认|备注|
|---|---|---|---|---|---|---|---|---|---|
|本地控制模式|LOCAL_CONTROL_MODE|400|BOOL|null|null|read|本地控制模式，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|远程控制模式|REMOTE_CONTROL_MODE|400|BOOL|null|null|read|远程控制模式，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|无人自动模式|AUTO_UNMANNED_MODE|400|BOOL|null|null|read|无人自动模式，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|无人点动模式|JOG_UNMANNED_MODE|400|BOOL|null|null|read|无人点动模式，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|通讯正常|COMMUNICATION_OK|400|BOOL|null|null|read|通讯正常，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|高压运行指示灯|HIGH_VOLTAGE_INDICATOR|400|BOOL|null|null|read|高压运行指示灯，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|整流运行指示灯|RECTIFIER_INDICATOR|400|BOOL|null|null|read|整流运行指示灯，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|挖掘模式指示灯|DIG_MODE_INDICATOR|400|BOOL|null|null|read|挖掘模式指示灯，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|行走模式指示灯|WALK_MODE_INDICATOR|400|BOOL|null|null|read|行走模式指示灯，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|提升/右行走松闸指示灯|LIFT_RIGHT_RELEASE_INDICATOR|400|BOOL|null|null|read|提升/右行走松闸指示灯，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|推压/左行走松闸指示灯|PUSH_LEFT_RELEASE_INDICATOR|400|BOOL|null|null|read|推压/左行走松闸指示灯，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|回转松闸指示灯|ROTATION_RELEASE_INDICATOR|400|BOOL|null|null|read|回转松闸指示灯，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|电铲故障指示灯|SHOVEL_FAULT_INDICATOR|400|BOOL|null|null|read|电铲故障指示灯，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|提升限位触发|LIFT_LIMIT_TRIGGERED|400|BOOL|null|null|read|提升限位触发，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|推压限位触发|PUSH_LIMIT_TRIGGERED|400|BOOL|null|null|read|推压限位触发，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|提升/右行走执行结果|LIFT_RIGHT_EXEC_RESULT|400|BOOL|null|null|read|提升/右行走执行结果，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|推压/左行走执行结果|PUSH_LEFT_EXEC_RESULT|400|BOOL|null|null|read|推压/左行走执行结果，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|回转执行结果|ROTATION_EXEC_RESULT|400|BOOL|null|null|read|回转执行结果，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|整流进线电压|RECTIFIER_INPUT_VOLTAGE|400|REAL|null|null|read|整流进线电压，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|直流母线电压|DC_BUS_VOLTAGE|400|REAL|null|null|read|直流母线电压，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|整流电流|RECTIFIER_CURRENT|400|REAL|null|null|read|整流电流，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|整流功率|RECTIFIER_POWER|400|REAL|null|null|read|整流功率，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|提升电机电压|LIFT_MOTOR_VOLTAGE|400|REAL|null|null|read|提升电机电压，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|提升电机电流|LIFT_MOTOR_CURRENT|400|REAL|null|null|read|提升电机电流，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|提升电机功率|LIFT_MOTOR_POWER|400|REAL|null|null|read|提升电机功率，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|提升电机转矩|LIFT_MOTOR_TORQUE|400|REAL|null|null|read|提升电机转矩，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|提升电机设定转速|LIFT_MOTOR_SET_SPEED|400|REAL|null|null|read|提升电机设定转速，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|提升电机实际转速|LIFT_MOTOR_ACTUAL_SPEED|400|REAL|null|null|read|提升电机实际转速，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|推压电机电压|PUSH_MOTOR_VOLTAGE|400|REAL|null|null|read|推压电机电压，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|推压电机电流|PUSH_MOTOR_CURRENT|400|REAL|null|null|read|推压电机电流，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|推压电机功率|PUSH_MOTOR_POWER|400|REAL|null|null|read|推压电机功率，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|推压电机转矩|PUSH_MOTOR_TORQUE|400|REAL|null|null|read|推压电机转矩，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|推压电机设定转速|PUSH_MOTOR_SET_SPEED|400|REAL|null|null|read|推压电机设定转速，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|推压电机实际转速|PUSH_MOTOR_ACTUAL_SPEED|400|REAL|null|null|read|推压电机实际转速，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|回转电机电压|ROTATION_MOTOR_VOLTAGE|400|REAL|null|null|read|回转电机电压，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|回转电机电流|ROTATION_MOTOR_CURRENT|400|REAL|null|null|read|回转电机电流，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|回转电机功率|ROTATION_MOTOR_POWER|400|REAL|null|null|read|回转电机功率，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|回转电机转矩|ROTATION_MOTOR_TORQUE|400|REAL|null|null|read|回转电机转矩，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|回转电机设定转速|ROTATION_MOTOR_SET_SPEED|400|REAL|null|null|read|回转电机设定转速，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|回转电机实际转速|ROTATION_MOTOR_ACTUAL_SPEED|400|REAL|null|null|read|回转电机实际转速，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|左行走电机电压|LEFT_WALK_MOTOR_VOLTAGE|400|REAL|null|null|read|左行走电机电压，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|左行走电机电流|LEFT_WALK_MOTOR_CURRENT|400|REAL|null|null|read|左行走电机电流，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|左行走电机功率|LEFT_WALK_MOTOR_POWER|400|REAL|null|null|read|左行走电机功率，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|左行走电机转矩|LEFT_WALK_MOTOR_TORQUE|400|REAL|null|null|read|左行走电机转矩，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|左行走电机设定转速|LEFT_WALK_MOTOR_SET_SPEED|400|REAL|null|null|read|左行走电机设定转速，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|左行走电机实际转速|LEFT_WALK_MOTOR_ACTUAL_SPEED|400|REAL|null|null|read|左行走电机实际转速，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|右行走电机电压|RIGHT_WALK_MOTOR_VOLTAGE|400|REAL|null|null|read|右行走电机电压，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|右行走电机电流|RIGHT_WALK_MOTOR_CURRENT|400|REAL|null|null|read|右行走电机电流，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|右行走电机功率|RIGHT_WALK_MOTOR_POWER|400|REAL|null|null|read|右行走电机功率，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|右行走电机转矩|RIGHT_WALK_MOTOR_TORQUE|400|REAL|null|null|read|右行走电机转矩，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|右行走电机设定转速|RIGHT_WALK_MOTOR_SET_SPEED|400|REAL|null|null|read|右行走电机设定转速，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|右行走电机实际转速|RIGHT_WALK_MOTOR_ACTUAL_SPEED|400|REAL|null|null|read|右行走电机实际转速，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|提升编码器|LIFT_ENCODER|400|REAL|null|null|read|提升编码器，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|推压编码器|PUSH_ENCODER|400|REAL|null|null|read|推压编码器，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|回转角度|ROTATION_ANGLE|400|REAL|null|null|read|回转角度，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|斗杆倾角|BUCKET_TILT_ANGLE|400|REAL|null|null|read|斗杆倾角，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|本地模式按钮|LOCAL_MODE_BUTTON|401|BOOL|null|null|write|本地模式按钮，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|远程模式按钮|REMOTE_MODE_BUTTON|401|BOOL|null|null|write|远程模式按钮，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|无人自动模式按钮|AUTO_UNMANNED_MODE_BUTTON|401|BOOL|null|null|write|无人自动模式按钮，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|无人点动模式按钮|JOG_UNMANNED_MODE_BUTTON|401|BOOL|null|null|write|无人点动模式按钮，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|通信心跳|COMMUNICATION_HEARTBEAT|401|UNKNOWN|null|null|write|通信心跳，单位待核|UNKNOWN_FROM_DATABASE|只有名称，类型与地址均无调用证据|
|高压启动|HIGH_VOLTAGE_START|401|BOOL|null|null|write|高压启动，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|高压停止|HIGH_VOLTAGE_STOP|401|BOOL|null|null|write|高压停止，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|整流启动|RECTIFIER_START|401|BOOL|null|null|write|整流启动，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|整流停止|RECTIFIER_STOP|401|BOOL|null|null|write|整流停止，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|急停按钮|EMERGENCY_STOP_BUTTON|401|BOOL|null|null|write|急停按钮，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|故障复位按钮|FAULT_RESET_BUTTON|401|BOOL|null|null|write|故障复位按钮，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|挖掘模式按钮|DIG_MODE_BUTTON|401|BOOL|null|null|write|挖掘模式按钮，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|行走模式按钮|WALK_MODE_BUTTON|401|BOOL|null|null|write|行走模式按钮，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|提升/右行走抱闸打开|LIFT_RIGHT_RELEASE_BRAKE_OPEN|401|BOOL|null|null|write|提升/右行走抱闸打开，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|提升/右行走闸关闭|LIFT_RIGHT_RELEASE_BRAKE_CLOSE|401|BOOL|null|null|write|提升/右行走闸关闭，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|推压/左行走闸打开|PUSH_LEFT_VALVE_OPEN|401|BOOL|null|null|write|推压/左行走闸打开，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|推压/左行走闸关闭|PUSH_LEFT_VALVE_CLOSE|401|BOOL|null|null|write|推压/左行走闸关闭，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|回转抱闸打开|ROTATION_BRAKE_OPEN|401|BOOL|null|null|write|回转抱闸打开，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|回转抱闸关闭|ROTATION_BRAKE_CLOSE|401|BOOL|null|null|write|回转抱闸关闭，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|提升向上/右行走向前|LIFT_UP_OR_RIGHT_FORWARD|401|BOOL|null|null|write|提升向上/右行走向前，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|提升向下/右行走向后|LIFT_DOWN_OR_RIGHT_BACKWARD|401|BOOL|null|null|write|提升向下/右行走向后，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|推压向前/左行走向前|PUSH_FORWARD_OR_LEFT_FORWARD|401|BOOL|null|null|write|推压向前/左行走向前，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|推压向后/左行走向后|PUSH_BACKWARD_OR_LEFT_BACKWARD|401|BOOL|null|null|write|推压向后/左行走向后，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|回转向左|ROTATION_LEFT|401|BOOL|null|null|write|回转向左，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|回转向右|ROTATION_RIGHT|401|BOOL|null|null|write|回转向右，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|开斗指令|BUCKET_OPEN_COMMAND|401|BOOL|null|null|write|开斗指令，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|喇叭指令|HORN_COMMAND|401|BOOL|null|null|write|喇叭指令，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|提升/右行走自动执行开始|LIFT_RIGHT_AUTO_START|401|BOOL|null|null|write|提升/右行走自动执行开始，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|推压/左行走自动执行开始|PUSH_LEFT_AUTO_START|401|BOOL|null|null|write|推压/左行走自动执行开始，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|回转自动执行开始|ROTATION_AUTO_START|401|BOOL|null|null|write|回转自动执行开始，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|提升/右行走目标位置|LIFT_RIGHT_TARGET_POSITION|401|REAL|null|null|write|提升/右行走目标位置，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|推压/左行走目标位置|PUSH_LEFT_TARGET_POSITION|401|REAL|null|null|write|推压/左行走目标位置，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|回转目标位置|ROTATION_TARGET_POSITION|401|REAL|null|null|write|回转目标位置，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|提升/右行走设定转速|LIFT_RIGHT_SET_SPEED|401|REAL|null|null|write|提升/右行走设定转速，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|推压/左行走设定转速|PUSH_LEFT_SET_SPEED|401|REAL|null|null|write|推压/左行走设定转速，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
|回转设定转速|ROTATION_SET_SPEED|401|REAL|null|null|write|回转设定转速，单位待核|UNKNOWN_FROM_DATABASE|DB/名称确认；具名地址未知|
