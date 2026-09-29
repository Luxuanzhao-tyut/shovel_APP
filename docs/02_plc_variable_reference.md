# PLC 正式 DB 变量参考（阶段二）

DB 地址只来自上位机通信点表，与 TIA I/Q/M 元数据独立。
CONFIRMED_FROM_EXCEL 表示原 Excel 的该行地址可确定；不代表已在现场验证。
本阶段全部 verification_status=NOT_TESTED_ON_PLC，真实写入持续禁止。

## 来源与等级

source_type：JAVA_SOURCE / JAVA_MYSQL_POINT_TABLE / TIA_GLOBAL_TAG_TABLE / LADDER_SCREENSHOT / INFERENCE。
confidence：VERIFIED_FROM_SOURCE / CONFIRMED_FROM_EXCEL / PARTIALLY_CONFIRMED / POSSIBLE_CANDIDATE / SOURCE_CONFLICT / SOURCE_CONFLICT_OR_INVALID / INVALID_IN_SOURCE / UNKNOWN / UNKNOWN_FROM_DATABASE。
VERIFIED_FROM_SOURCE 只指来源存在性；VERIFIED_ON_PLC 才表示现场测试，但本次没有任何此类结果。
formal valid_address=true 只接受正式 DB 来源和完整合法偏移；候选、冲突、TIA 和推断均不能进入 reader/writer。

## 数量与关键地址

DB400：70 行（56 具名反馈、14 备用）=32 BOOL+38 REAL，全部地址可据表读取。
DB401：47 行=41 BOOL+6 REAL；24 BOOL 与6 REAL地址可信；1非法BOOL和16后续BOOL隔离。
有效具名业务地址为 DB400 56 + DB401 30；“地址可靠”不是允许真实控制。
REAL: lift_encoder=142，push_encoder=146，swing_angle=150，bucket_tilt_angle=154；三轴实际速度=42/66/90。
DB400 从0开始读取需要至少158字节，代码按配置计算，不固定截为155。
未填写来源未说明的单位。回转角度保留右正左负，不归一化为0..360。

## 完整映射

|Python名称|来源名称|DB|类型|byte|bit|方向|confidence|有效地址|来源单元格|原始备注|
|---|---|---|---|---|---|---|---|---|---|---|
|local_mode|本地控制模式|400|BOOL|0|0|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B4:E4||
|rectifier_input_voltage|整流进线电压|400|REAL|6|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H4:K4||
|remote_mode|远程控制模式|400|BOOL|0|1|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B5:E5||
|dc_bus_voltage|直流母线电压|400|REAL|10|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H5:K5||
|auto_unmanned_mode|无人自动模式|400|BOOL|0|2|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B6:E6|用于执行规划给的轨迹|
|rectifier_current|整流电流|400|REAL|14|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H6:K6||
|jog_unmanned_mode|无人点动模式|400|BOOL|0|3|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B7:E7|用于手动设置目标位置|
|rectifier_power|整流功率|400|REAL|18|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H7:K7||
|communication_ok|通讯正常|400|BOOL|0|4|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B8:E8||
|lift_motor_voltage|提升电机电压|400|REAL|22|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H8:K8|V|
|high_voltage_indicator|高压运行指示灯|400|BOOL|0|5|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B9:E9|样机没高压，真机有，备用点位|
|lift_current|提升电机电流|400|REAL|26|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H9:K9|A|
|rectifier_indicator|整流运行指示灯|400|BOOL|0|6|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B10:E10||
|lift_motor_power|提升电机功率|400|REAL|30|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H10:K10|kW|
|dig_mode|挖掘模式指示灯|400|BOOL|0|7|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B11:E11|挖掘模式为1时，提升、推压有效<br>行走模式为1时，左、右行走有效|
|lift_torque|提升电机转矩|400|REAL|34|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H11:K11|Nm|
|propel_mode|行走模式指示灯|400|BOOL|1|0|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B12:E12||
|lift_motor_set_speed|提升电机设定转速|400|REAL|38|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H12:K12|Rpm|
|lift_right_release_indicator|提升/右行走松闸指示灯|400|BOOL|1|1|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B13:E13||
|lift_actual_speed|提升电机实际转速|400|REAL|42|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H13:K13|Rpm|
|push_left_release_indicator|推压/左行走松闸指示灯|400|BOOL|1|2|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B14:E14||
|push_motor_voltage|推压电机电压|400|REAL|46|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H14:K14||
|rotation_release_indicator|回转松闸指示灯|400|BOOL|1|3|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B15:E15||
|push_current|推压电机电流|400|REAL|50|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H15:K15||
|fault|电铲故障指示灯|400|BOOL|1|4|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B16:E16||
|push_motor_power|推压电机功率|400|REAL|54|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H16:K16||
|lift_limit_triggered|提升限位触发|400|BOOL|1|5|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B17:E17||
|push_torque|推压电机转矩|400|REAL|58|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H17:K17||
|push_limit_triggered|推压限位触发|400|BOOL|1|6|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B18:E18||
|push_motor_set_speed|推压电机设定转速|400|REAL|62|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H18:K18||
|lift_right_exec_result|提升/右行走执行结果|400|BOOL|1|7|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B19:E19||
|push_actual_speed|推压电机实际转速|400|REAL|66|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H19:K19||
|push_left_exec_result|推压/左行走执行结果|400|BOOL|2|0|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B20:E20||
|rotation_motor_voltage|回转电机电压|400|REAL|70|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H20:K20||
|rotation_exec_result|回转执行结果|400|BOOL|2|1|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B21:E21||
|swing_current|回转电机电流|400|REAL|74|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H21:K21||
|db400_reserved_2_2|备用|400|BOOL|2|2|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B22:E22||
|rotation_motor_power|回转电机功率|400|REAL|78|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H22:K22||
|db400_reserved_2_3|备用|400|BOOL|2|3|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B23:E23||
|swing_torque|回转电机转矩|400|REAL|82|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H23:K23||
|db400_reserved_2_4|备用|400|BOOL|2|4|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B24:E24||
|rotation_motor_set_speed|回转电机设定转速|400|REAL|86|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H24:K24||
|db400_reserved_2_5|备用|400|BOOL|2|5|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B25:E25||
|swing_actual_speed|回转电机实际转速|400|REAL|90|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H25:K25||
|db400_reserved_2_6|备用|400|BOOL|2|6|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B26:E26||
|left_walk_motor_voltage|左行走电机电压|400|REAL|94|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H26:K26||
|db400_reserved_2_7|备用|400|BOOL|2|7|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B27:E27||
|left_walk_motor_current|左行走电机电流|400|REAL|98|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H27:K27||
|db400_reserved_3_0|备用|400|BOOL|3|0|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B28:E28||
|left_walk_motor_power|左行走电机功率|400|REAL|102|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H28:K28||
|db400_reserved_3_1|备用|400|BOOL|3|1|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B29:E29||
|left_walk_motor_torque|左行走电机转矩|400|REAL|106|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H29:K29||
|db400_reserved_3_2|备用|400|BOOL|3|2|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B30:E30||
|left_walk_motor_set_speed|左行走电机设定转速|400|REAL|110|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H30:K30||
|db400_reserved_3_3|备用|400|BOOL|3|3|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B31:E31||
|left_walk_motor_actual_speed|左行走电机实际转速|400|REAL|114|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H31:K31||
|db400_reserved_3_4|备用|400|BOOL|3|4|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B32:E32||
|right_walk_motor_voltage|右行走电机电压|400|REAL|118|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H32:K32||
|db400_reserved_3_5|备用|400|BOOL|3|5|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B33:E33||
|right_walk_motor_current|右行走电机电流|400|REAL|122|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H33:K33||
|db400_reserved_3_6|备用|400|BOOL|3|6|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B34:E34||
|right_walk_motor_power|右行走电机功率|400|REAL|126|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H34:K34||
|db400_reserved_3_7|备用|400|BOOL|3|7|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!B35:E35||
|right_walk_motor_torque|右行走电机转矩|400|REAL|130|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H35:K35||
|right_walk_motor_set_speed|右行走电机设定转速|400|REAL|134|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H36:K36||
|right_walk_motor_actual_speed|右行走电机实际转速|400|REAL|138|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H37:K37||
|lift_encoder|提升编码器|400|REAL|142|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H38:K38|提升向下数值增大|
|push_encoder|推压编码器|400|REAL|146|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H39:K39|推压向前数值增大|
|swing_angle|回转角度|400|REAL|150|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H40:K40|铲斗在履带中心向前为0°，右转为正，左转为负|
|bucket_tilt_angle|斗杆倾角|400|REAL|154|None|read|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲发送!H41:K41|斗杆水平为0°，向下为正，向上为负|
|local_mode_button|本地模式按钮|401|BOOL|0|0|write|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲接收!B3:E3|四种模式为互斥|
|lift_right_target_position|提升/右行走目标位置|401|REAL|6|None|write|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲接收!H3:K3|提升为提升编码器值|
|remote_mode_button|远程模式按钮|401|BOOL|0|1|write|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲接收!B4:E4||
|push_left_target_position|推压/左行走目标位置|401|REAL|10|None|write|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲接收!H4:K4|推压编码器值|
|auto_unmanned_mode_button|无人自动模式按钮|401|BOOL|0|2|write|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲接收!B5:E5||
|rotation_target_position|回转目标位置|401|REAL|14|None|write|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲接收!H5:K5|回转角度值|
|jog_unmanned_mode_button|无人点动模式按钮|401|BOOL|0|3|write|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲接收!B6:E6||
|lift_right_set_speed|提升/右行走设定转速|401|REAL|18|None|write|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲接收!H6:K6|提升向下为正/右行走向前为正|
|communication_heartbeat|通信心跳|401|BOOL|0|4|write|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲接收!B7:E7|以10Hz，发送0-1-0-1|
|push_left_set_speed|推压/左行走设定转速|401|REAL|22|None|write|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲接收!H7:K7|推压向前为正/左行走向前为正|
|high_voltage_start|高压启动|401|BOOL|0|5|write|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲接收!B8:E8|样机没高压，真机有，备用点位|
|rotation_set_speed|回转设定转速|401|REAL|26|None|write|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲接收!H8:K8|右转为正|
|high_voltage_stop|高压停止|401|BOOL|0|6|write|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲接收!B9:E9||
|rectifier_start|整流启动|401|BOOL|0|7|write|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲接收!B10:E10||
|rectifier_stop|整流停止|401|BOOL|1|0|write|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲接收!B11:E11||
|emergency_stop_button|急停按钮|401|BOOL|1|1|write|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲接收!B12:E12||
|fault_reset_button|故障复位按钮|401|BOOL|1|2|write|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲接收!B13:E13||
|dig_mode_button|挖掘模式按钮|401|BOOL|1|3|write|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲接收!B14:E14||
|walk_mode_button|行走模式按钮|401|BOOL|1|4|write|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲接收!B15:E15||
|lift_right_release_brake_open|提升/右行走抱闸打开|401|BOOL|1|5|write|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲接收!B16:E16||
|lift_right_release_brake_close|提升/右行走闸关闭|401|BOOL|1|6|write|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲接收!B17:E17||
|push_left_valve_open|推压/左行走闸打开|401|BOOL|1|7|write|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲接收!B18:E18||
|push_left_valve_close|推压/左行走闸关闭|401|BOOL|2|0|write|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲接收!B19:E19||
|rotation_brake_open|回转抱闸打开|401|BOOL|2|1|write|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲接收!B20:E20||
|rotation_brake_close|回转抱闸关闭|401|BOOL|2|2|write|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲接收!B21:E21||
|lift_up_or_right_forward|提升向上/右行走向前|401|BOOL|2|3|write|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲接收!B22:E22||
|lift_down_or_right_backward|提升向下/右行走向后|401|BOOL|2|4|write|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲接收!B23:E23||
|push_forward_or_left_forward|推压向前/左行走向前|401|BOOL|2|5|write|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲接收!B24:E24||
|push_backward_or_left_backward|推压向后/左行走向后|401|BOOL|2|6|write|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲接收!B25:E25||
|rotation_left|回转向左|401|BOOL|2|7|write|CONFIRMED_FROM_EXCEL|True|太理数据对接0612.xlsx / 电铲接收!B26:E26||
|rotation_right|回转向右|401|BOOL|None|None|write|INVALID_IN_SOURCE|False|太理数据对接0612.xlsx / 电铲接收!B27:E27|；原始 2.8 非法，未进位、未顺延|
|bucket_open_command|开斗指令|401|BOOL|None|None|write|SOURCE_CONFLICT_OR_INVALID|False|太理数据对接0612.xlsx / 电铲接收!B28:E28|；位于非法 2.8 后方，缺独立证据确认是否整体错位，隔离原地址|
|horn_command|喇叭指令|401|BOOL|None|None|write|SOURCE_CONFLICT_OR_INVALID|False|太理数据对接0612.xlsx / 电铲接收!B29:E29|；位于非法 2.8 后方，缺独立证据确认是否整体错位，隔离原地址|
|lift_right_auto_start|提升/右行走自动执行开始|401|BOOL|None|None|write|SOURCE_CONFLICT_OR_INVALID|False|太理数据对接0612.xlsx / 电铲接收!B30:E30|；位于非法 2.8 后方，缺独立证据确认是否整体错位，隔离原地址|
|push_left_auto_start|推压/左行自动走执行开始|401|BOOL|None|None|write|SOURCE_CONFLICT_OR_INVALID|False|太理数据对接0612.xlsx / 电铲接收!B31:E31|；位于非法 2.8 后方，缺独立证据确认是否整体错位，隔离原地址；Excel原文“推压/左行自动走执行开始”与Java名称不同，仅候选关联|
|rotation_auto_start|回转自动执行开始|401|BOOL|None|None|write|SOURCE_CONFLICT_OR_INVALID|False|太理数据对接0612.xlsx / 电铲接收!B32:E32|；位于非法 2.8 后方，缺独立证据确认是否整体错位，隔离原地址|
|db401_reserved_3_5|备用|401|BOOL|None|None|write|SOURCE_CONFLICT_OR_INVALID|False|太理数据对接0612.xlsx / 电铲接收!B33:E33|；位于非法 2.8 后方，缺独立证据确认是否整体错位，隔离原地址|
|db401_reserved_3_6|备用|401|BOOL|None|None|write|SOURCE_CONFLICT_OR_INVALID|False|太理数据对接0612.xlsx / 电铲接收!B34:E34|；位于非法 2.8 后方，缺独立证据确认是否整体错位，隔离原地址|
|db401_reserved_3_7|备用|401|BOOL|None|None|write|SOURCE_CONFLICT_OR_INVALID|False|太理数据对接0612.xlsx / 电铲接收!B35:E35|；位于非法 2.8 后方，缺独立证据确认是否整体错位，隔离原地址|
|db401_reserved_4_0|备用|401|BOOL|None|None|write|SOURCE_CONFLICT_OR_INVALID|False|太理数据对接0612.xlsx / 电铲接收!B36:E36|；位于非法 2.8 后方，缺独立证据确认是否整体错位，隔离原地址|
|db401_reserved_4_1|备用|401|BOOL|None|None|write|SOURCE_CONFLICT_OR_INVALID|False|太理数据对接0612.xlsx / 电铲接收!B37:E37|；位于非法 2.8 后方，缺独立证据确认是否整体错位，隔离原地址|
|db401_reserved_4_2|备用|401|BOOL|None|None|write|SOURCE_CONFLICT_OR_INVALID|False|太理数据对接0612.xlsx / 电铲接收!B38:E38|；位于非法 2.8 后方，缺独立证据确认是否整体错位，隔离原地址|
|db401_reserved_4_3|备用|401|BOOL|None|None|write|SOURCE_CONFLICT_OR_INVALID|False|太理数据对接0612.xlsx / 电铲接收!B39:E39|；位于非法 2.8 后方，缺独立证据确认是否整体错位，隔离原地址|
|db401_reserved_4_4|备用|401|BOOL|None|None|write|SOURCE_CONFLICT_OR_INVALID|False|太理数据对接0612.xlsx / 电铲接收!B40:E40|；位于非法 2.8 后方，缺独立证据确认是否整体错位，隔离原地址|
|db401_reserved_4_5|备用|401|BOOL|None|None|write|SOURCE_CONFLICT_OR_INVALID|False|太理数据对接0612.xlsx / 电铲接收!B41:E41|；位于非法 2.8 后方，缺独立证据确认是否整体错位，隔离原地址|
|db401_reserved_4_6|备用|401|BOOL|None|None|write|SOURCE_CONFLICT_OR_INVALID|False|太理数据对接0612.xlsx / 电铲接收!B42:E42|；位于非法 2.8 后方，缺独立证据确认是否整体错位，隔离原地址|
|db401_reserved_4_7|备用|401|BOOL|None|None|write|SOURCE_CONFLICT_OR_INVALID|False|太理数据对接0612.xlsx / 电铲接收!B43:E43|；位于非法 2.8 后方，缺独立证据确认是否整体错位，隔离原地址|

## 隔离项与接口限制

回转向右原始地址2.8保存在 raw_source_address，正式 byte/bit=null，INVALID_IN_SOURCE。
其后的开斗、喇叭、三轴自动开始和11个备用BOOL一并隔离；没有将2.8进位至3.0，也没有移动后续位。
Excel“推压/左行自动走执行开始”与Java名称不同，只保留候选关联，不能当作已确认同一信号。
目标REAL接口存在，PLC internal closed-loop implementation=UNKNOWN。需梯形图确认比较、速度输出、反馈、减速/停车、完成及握手。
DB401通信心跳0.4：原表“以10Hz，发送0-1-0-1”；记录但不自动启动。
