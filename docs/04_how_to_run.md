# 本阶段仅离线运行

在工程根目录用`.venv/Scripts/python.exe`。测试命令`python -m pytest`，无需真实PLC。
例02 --offline经过具名reader读取1234.5；例03/04 --offline --count 3打印/保存空状态；例05/06/07/08都是离线预览。01只允许--help或静态检查，本次未连接。

# 下一次现场顺序

1. PLC实际IP已确认：192.168.2.20。Excel中的192.168.0.10仅保留为历史来源，不再作为连接候选。
2. 经确认后在配置填写active_ip，保留两个来源IP，填site_ip_confirmed=true、ip_status=CONFIRMED_BY_OPERATOR、site_confirmation_note（确认人/依据/时间）。本阶段未做这一步。
3. 运行例01，只连接/断开，无业务读写。
4. 运行例02，只读DB400.DBD142并核对TIA/Java。
5. 现场人员按设备既有安全规程小幅操作提升，观察Python数值同步与方向；再分别只读146和150。
6. 单点交叉核对通过后再试例03/04，--count 0持续至Ctrl+C。

第一阶段现场不写PLC、不自动心跳、不松闸。IP“已确认”不会解锁写入。

# 运行结果含义

CONFIRMED_FROM_EXCEL：地址有来源，非现场验证。NOT_TESTED_ON_PLC不能标成VERIFIED_ON_PLC。
INVALID_IN_SOURCE / SOURCE_CONFLICT_OR_INVALID：原始来源有问题，正式偏移隔离，不能用于I/O。
POSSIBLE_CANDIDATE：只能交叉引用研究，不能给reader/writer当地址。
None / 空CSV：未知，不是零；offline_empty：空状态演示，不是实测；offline_fixture：合成字节验证。
bulk按有效变量末端计算到158字节，短读即报错，不补零。

# 工具与依赖

正式运行依赖requirements.txt；本次未改变通信库版本。tools/audit_excel_sources.py是额外的只读提取工具，使用带openpyxl的审计Python环境（本次为桌面内置Python），输出data/excel_source_audit.json，不改Excel也不自动修改正式映射。不是每次启动必跑步骤。
新增来源时先重新审计与人工确认冲突，不依赖名称或行顺序自动升级可信度。
