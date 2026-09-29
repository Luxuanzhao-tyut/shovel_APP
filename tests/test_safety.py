"""真实写控制器的离线内存测试。不会连接网络或样机。"""
import struct
import time
import pytest
from plc.config import load_config
from plc.live_control import LiveControlManager, VerifiedDB401Writer
from plc.variable_map import load_variable_map
from models.shovel_state import ShovelState


class MemoryClient:
    def __init__(self,config):
        self.config=config; self.online=True; self.dbs={401:bytearray(256)}; self.writes=[]
    def is_connected(self): return self.online
    def read_bytes(self,db,offset,size): return bytes(self.dbs.setdefault(db,bytearray(256))[offset:offset+size])
    def write_bytes(self,db,offset,data):
        if self.config['safety']['write_enabled'] is not True or self.config['safety']['dry_run'] is not False:
            raise RuntimeError('真实写入拒绝：当前会话未武装')
        self.dbs.setdefault(db,bytearray(256))[offset:offset+len(data)]=data; self.writes.append((db,offset,bytes(data)))


def safe_state(**kw):
    base=dict(remote_mode=True,local_mode=False,communication_ok=True,fault=False,dig_mode=True,propel_mode=False,
              high_voltage_indicator=True,rectifier_indicator=True,lift_right_release_indicator=True,
              push_left_release_indicator=True,rotation_release_indicator=True,lift_limit_triggered=False,push_limit_triggered=False)
    base.update(kw); return ShovelState(**base)


def make_manager(state=None):
    config=load_config(); config['live_control']['heartbeat_period_ms']=10000; config['live_control']['legacy_pulse_ms']=50
    config['live_control']['drive_fault_reset_pulse_ms']=10
    config['live_control']['drive_fault_reset_settle_ms']=80
    config['live_control']['drive_fault_reset_retries']=1
    config['live_control']['brake_feedback_timeout_ms']=120
    config['live_control']['brake_release_retries']=1
    config['live_control']['mode_brake_wait_ms']=200
    config['live_control']['mode_switch_timeout_ms']=600
    config['live_control']['auto_target_poll_ms']=20
    config['live_control']['auto_target_timeout_s']=1.5
    config['live_control']['auto_target_encoder_tolerance']=20
    config['live_control']['auto_target_swing_tolerance_deg']=1.0
    config['live_control']['auto_target_encoder_wrong_way_margin']=40
    config['live_control']['auto_target_swing_wrong_way_margin_deg']=2.0
    config['live_control']['auto_target_max_percent']=5.0
    client=MemoryClient(config); holder={'state':state or safe_state(),'t':None}
    mgr=LiveControlManager(client,config,load_variable_map(),lambda:holder['state'],lambda:None if holder['t'] is None else time.monotonic()-holder['t'])
    # Timestamp must represent arrival of the simulated DB400 frame, not the start of
    # manager/config construction.  Fresh Windows virtualenvs can make imports/init
    # exceed the 600 ms production freshness threshold.
    holder['t']=time.monotonic()
    return mgr,client,holder


def arm(mgr):
    mgr.arm('现场已清场，硬急停可用',{'area_clear':True,'hard_estop_ready':True,'control_authority':True,'low_speed_test':True})


def test_bool_rmw_preserves_other_bits_and_readback():
    mgr,client,_=make_manager(); arm(mgr)
    client.dbs[401][3]=0b10101010
    mgr.writer.write_bool('bucket_open_command',True)
    assert client.dbs[401][3] & 0b10
    assert client.dbs[401][3] & 0b10101000 == 0b10101000
    mgr.disarm()


def test_real_write_big_endian_and_readback():
    mgr,client,_=make_manager(); arm(mgr)
    mgr.writer.write_real('lift_right_set_speed',2.5)
    assert bytes(client.dbs[401][18:22])==struct.pack('>f',2.5)
    mgr.disarm()


def test_arm_requires_phrase_and_all_confirmations():
    mgr,_,_=make_manager()
    with pytest.raises(RuntimeError,match='口令'): mgr.arm('错',{'area_clear':True,'hard_estop_ready':True,'control_authority':True,'low_speed_test':True})
    with pytest.raises(RuntimeError,match='未全部'): mgr.arm('现场已清场，硬急停可用',{'area_clear':True})


def test_motion_requires_remote_comm_fault_rectifier_mode_and_brake():
    mgr,_,holder=make_manager(safe_state(remote_mode=False)); arm(mgr)
    with pytest.raises(RuntimeError,match='远程'): mgr.jog_start('lift','up',2.0)
    holder['state']=safe_state(remote_mode=True,dig_mode=False)
    with pytest.raises(RuntimeError,match='挖掘'): mgr.jog_start('lift','up',2.0)
    holder['state']=safe_state(lift_right_release_indicator=False)
    with pytest.raises(RuntimeError,match='松闸'): mgr.jog_start('lift','up',2.0)
    mgr.disarm()



def test_rectifier_start_does_not_require_plc_communication_ok_feedback():
    mgr,client,_=make_manager(safe_state(communication_ok=False, rectifier_indicator=False)); arm(mgr)
    client.writes.clear()
    mgr.pulse('rectifier_start')
    # DB401.DBX0.7 脉冲最终复位 FALSE。
    assert (client.dbs[401][0] & (1 << 7)) == 0
    assert any(offset == 0 for _db, offset, _data in client.writes)
    mgr.disarm()


def test_rectifier_start_allows_stale_aggregate_fault_when_direct_sources_clear():
    # 新逻辑：DB400 汇总 fault=True 不能单独证明真实驱动故障。
    # 当 7 个 FC199 原始故障源全部为 FALSE 时，允许整流启动继续执行。
    mgr,client,_=make_manager(safe_state(communication_ok=False, fault=True, rectifier_indicator=False)); arm(mgr)
    client.writes.clear()
    mgr.pulse('rectifier_start')
    assert (client.dbs[401][0] & (1 << 7)) == 0
    mgr.disarm()


def test_rectifier_start_rejects_real_direct_fault_source():
    # 真实原始故障仍必须拒绝。这里模拟 DB16.DBX21.0 整流/ALM故障。
    mgr,client,_=make_manager(safe_state(communication_ok=False, fault=True, rectifier_indicator=False)); arm(mgr)
    client.dbs.setdefault(16, bytearray(256))[21] |= 0x01
    with pytest.raises(RuntimeError, match='整流/ALM'):
        mgr.pulse('rectifier_start')
    mgr.disarm()



def test_rectifier_start_ignores_motor_drive_faults_before_power_on():
    # 启动阶段：提升/推压等驱动未上电或未就绪，不应反过来阻止整流上电。
    mgr,client,_=make_manager(safe_state(communication_ok=False, fault=True, rectifier_indicator=False)); arm(mgr)
    # DB11/DB12 的直接故障源置 TRUE，模拟现场报“提升驱动、推压驱动”。
    client.dbs.setdefault(11, bytearray(256))[101] |= 0x01
    client.dbs.setdefault(12, bytearray(256))[101] |= 0x01
    # DB16 整流/ALM仍为 FALSE。
    mgr.pulse('rectifier_start')
    assert (client.dbs[401][0] & (1 << 7)) == 0
    mgr.disarm()


def test_drive_fault_reset_uses_confirmed_db28_remote_reset_bit():
    state = safe_state(
        communication_ok=True, fault=True, rectifier_indicator=True, dig_mode=True
    )
    mgr,client,_=make_manager(state); arm(mgr)
    mgr.reset_drive_faults(retries=1)
    # DB28.DBX100.5 最终必须回到 FALSE，且写历史中确实出现 DB28 byte100。
    assert (client.dbs.setdefault(28, bytearray(256))[100] & (1 << 5)) == 0
    assert any(db == 28 and offset == 100 for db, offset, _data in client.writes)
    mgr.disarm()


def test_brake_release_returns_success_only_with_real_feedback():
    state = safe_state(
        communication_ok=True,
        fault=False,
        rectifier_indicator=True,
        dig_mode=True,
        lift_right_release_indicator=True,
    )
    mgr,client,_=make_manager(state); arm(mgr)
    result = mgr.pulse('lift_right_release_brake_open')
    assert result['kind'] == 'LIVE_BRAKE_RELEASE_CONFIRMED'
    mgr.disarm()


def test_brake_release_fails_when_plc_feedback_stays_false():
    state = safe_state(
        communication_ok=True,
        fault=False,
        rectifier_indicator=True,
        dig_mode=True,
        lift_right_release_indicator=False,
    )
    mgr,client,_=make_manager(state); arm(mgr)
    with pytest.raises(RuntimeError, match='未反馈实际松闸'):
        mgr.pulse('lift_right_release_brake_open')
    mgr.disarm()


def test_brake_release_still_rejects_rectifier_alm_fault():
    state = safe_state(
        communication_ok=True,
        fault=True,
        rectifier_indicator=True,
        dig_mode=True,
        propel_mode=False,
    )
    mgr,client,_=make_manager(state); arm(mgr)
    client.dbs.setdefault(16, bytearray(256))[21] |= 0x01
    with pytest.raises(RuntimeError, match='整流/ALM'):
        mgr.pulse('lift_right_release_brake_open')
    mgr.disarm()


def test_mode_switch_not_blocked_by_motor_drive_fault_sources():
    state = safe_state(
        communication_ok=True,
        fault=True,
        rectifier_indicator=True,
        dig_mode=True,
        propel_mode=False,
        lift_right_release_indicator=False,
        push_left_release_indicator=False,
        rotation_release_indicator=False,
    )
    mgr,client,holder=make_manager(state); arm(mgr)
    client.dbs.setdefault(11, bytearray(256))[101] |= 0x01
    client.dbs.setdefault(12, bytearray(256))[101] |= 0x01

    import threading
    def plc_feedback():
        time.sleep(0.12)
        holder['state'] = safe_state(
            communication_ok=True, fault=True,
            dig_mode=False, propel_mode=True,
            lift_right_release_indicator=False,
            push_left_release_indicator=False,
            rotation_release_indicator=False,
        )
        holder['t'] = time.monotonic()
    threading.Thread(target=plc_feedback, daemon=True).start()

    result = mgr.pulse('walk_mode_button')
    assert result['kind'] == 'LIVE_MODE_SWITCH_CONFIRMED'
    mgr.disarm()

def test_fault_reset_is_allowed_when_communication_ok_feedback_is_false():
    mgr,client,_=make_manager(safe_state(communication_ok=False, fault=True)); arm(mgr)
    client.writes.clear()
    mgr.pulse('fault_reset_button')
    # DB401.DBX1.2 脉冲最终复位 FALSE。
    assert (client.dbs[401][1] & (1 << 2)) == 0
    mgr.disarm()


def test_lift_limit_blocks_up_but_allows_down_escape():
    mgr,client,_=make_manager(safe_state(lift_limit_triggered=True)); arm(mgr)
    with pytest.raises(RuntimeError,match='提升限位'): mgr.jog_start('lift','up',2.0)
    mgr.jog_start('lift','down',2.0)
    assert struct.unpack('>f',bytes(client.dbs[401][18:22]))[0] == pytest.approx(2.0)
    mgr.jog_stop('lift'); mgr.disarm()


def test_push_limit_blocks_configured_direction_but_allows_escape():
    mgr,client,_=make_manager(safe_state(push_limit_triggered=True)); arm(mgr)
    mgr.config.setdefault('operator_settings', {}).setdefault('limits', {})['push_blocked_direction'] = 'forward'
    with pytest.raises(RuntimeError,match='推压限位'): mgr.jog_start('push','forward',2.0)
    mgr.jog_start('push','backward',2.0)
    assert struct.unpack('>f',bytes(client.dbs[401][22:26]))[0] == pytest.approx(-2.0)
    mgr.jog_stop('push'); mgr.disarm()


def test_running_lift_stops_immediately_when_limit_frame_arrives():
    mgr,client,holder=make_manager(safe_state(lift_limit_triggered=False)); arm(mgr)
    mgr.jog_start('lift','up',2.0)
    assert struct.unpack('>f',bytes(client.dbs[401][18:22]))[0] == pytest.approx(-2.0)
    holder['state']=safe_state(lift_limit_triggered=True)
    events=mgr.handle_state_update(holder['state'])
    assert events and events[0]['axis']=='lift'
    assert struct.unpack('>f',bytes(client.dbs[401][18:22]))[0] == pytest.approx(0.0)
    assert (client.dbs[401][2] & ((1<<3)|(1<<4))) == 0
    mgr.disarm()


def test_running_push_stops_when_configured_limit_direction_trips():
    mgr,client,holder=make_manager(safe_state(push_limit_triggered=False)); arm(mgr)
    mgr.config.setdefault('operator_settings', {}).setdefault('limits', {})['push_blocked_direction'] = 'forward'
    mgr.jog_start('push','forward',2.0)
    holder['state']=safe_state(push_limit_triggered=True)
    events=mgr.handle_state_update(holder['state'])
    assert events and events[0]['axis']=='push'
    assert struct.unpack('>f',bytes(client.dbs[401][22:26]))[0] == pytest.approx(0.0)
    assert (client.dbs[401][2] & ((1<<5)|(1<<6))) == 0
    mgr.disarm()


def test_limit_does_not_stop_escape_direction():
    mgr,client,holder=make_manager(safe_state(lift_limit_triggered=True)); arm(mgr)
    mgr.jog_start('lift','down',2.0)
    events=mgr.handle_state_update(holder['state'])
    assert events == []
    assert struct.unpack('>f',bytes(client.dbs[401][18:22]))[0] == pytest.approx(2.0)
    mgr.jog_stop('lift'); mgr.disarm()


def test_jog_start_speed_then_direction_and_stop_direction_then_zero():
    mgr,client,_=make_manager(); arm(mgr); client.writes.clear()
    mgr.jog_start('lift','up',2.0)
    # 第一写应是 DBD18；第二写方向所在 byte2
    assert client.writes[0][1]==18 and client.writes[1][1]==2
    client.writes.clear(); mgr.jog_stop('lift')
    assert client.writes[0][1]==2 and client.writes[1][1]==18
    assert struct.unpack('>f',bytes(client.dbs[401][18:22]))[0]==0.0
    mgr.disarm()


def test_walk_pair_uses_one_8byte_speed_write_and_one_direction_byte_write():
    mgr,client,holder=make_manager(safe_state(dig_mode=False,propel_mode=True)); arm(mgr); client.writes.clear()
    mgr.walk_pair_start('forward',2.0,3.0)
    assert client.writes[0][1]==18 and len(client.writes[0][2])==8
    assert client.writes[1][1]==2 and len(client.writes[1][2])==1
    mgr.walk_pair_stop(); mgr.disarm()


def test_speed_limit_is_commissioning_limited():
    mgr,_,_=make_manager(); arm(mgr)
    limit = float(mgr.config['operator_settings']['speed']['max_percent'])
    with pytest.raises(RuntimeError,match='限幅'): mgr.jog_start('lift','up',limit + 1.0)
    mgr.disarm()


def test_stale_state_blocks_start_but_safe_stop_still_allowed():
    mgr,client,holder=make_manager(); arm(mgr); holder['t']=time.monotonic()-2
    with pytest.raises(RuntimeError,match='过期'): mgr.jog_start('lift','up',2.0)
    mgr.safe_stop_all(); mgr.disarm()


def test_select_remote_is_same_byte_group_rmw_and_requires_quiescent():
    mgr,client,holder=make_manager(safe_state(remote_mode=False,local_mode=True,communication_ok=True)); arm(mgr); client.writes.clear()
    mgr.select_remote()
    assert any(db == 401 and offset == 0 and len(data) == 1 for db, offset, data in client.writes)
    assert any(db == 28 and offset == 101 for db, offset, data in client.writes)
    assert (client.dbs[401][0]&0b1)==0 and (client.dbs[401][0]&0b10)==0b10
    mgr.disarm()


def test_aux_false_is_allowed_even_after_fault_to_deassert_output():
    mgr,client,holder=make_manager(); arm(mgr)
    mgr.set_aux_hold('horn_command',True)
    holder['state']=safe_state(fault=True)
    mgr.set_aux_hold('horn_command',False)
    assert (client.dbs[401][3] & (1<<2))==0
    mgr.disarm()


def test_disarm_cancels_active_pulse_and_clears_true_bit():
    import threading
    mgr,client,_=make_manager(); mgr.config['live_control']['legacy_pulse_ms']=500; arm(mgr)
    t=threading.Thread(target=lambda:mgr.pulse('fault_reset_button'))
    t.start(); time.sleep(0.05)
    assert client.dbs[401][1] & (1<<2)
    mgr.disarm(); t.join(timeout=1.0)
    assert (client.dbs[401][1] & (1<<2))==0
    assert mgr.armed is False and mgr.config['safety']['write_enabled'] is False


def test_disarm_clears_auxiliary_hold_outputs():
    mgr,client,_=make_manager(); arm(mgr)
    mgr.set_aux_hold('horn_command',True)
    mgr.set_aux_hold('bucket_open_command',True)
    assert client.dbs[401][3] & ((1<<1)|(1<<2))
    mgr.disarm()
    assert (client.dbs[401][3] & ((1<<1)|(1<<2)))==0


def test_execute_auto_target_pc_loop_stops_when_lift_reaches_target():
    mgr,client,holder=make_manager(safe_state(lift_encoder=7000.0)); arm(mgr)
    client.writes.clear()

    import threading
    def plc_feedback():
        # 提升目标 7100，编码器向下应增大。
        for value in (7030.0, 7060.0, 7090.0):
            time.sleep(0.04)
            holder['state'] = safe_state(lift_encoder=value)
            holder['t'] = time.monotonic()
    threading.Thread(target=plc_feedback, daemon=True).start()

    result = mgr.execute_auto_target('lift', 7100.0, 2.0)
    assert result['status'] == 'reached'
    # 不再触发 PLC auto-start DBX3.3。
    assert (client.dbs[401][3] & (1 << 3)) == 0
    # 最终方向必须清零、速度必须回 0。
    assert (client.dbs[401][2] & ((1 << 3) | (1 << 4))) == 0
    assert struct.unpack('>f', bytes(client.dbs[401][18:22]))[0] == pytest.approx(0.0)
    mgr.disarm()


def test_execute_auto_target_push_lower_target_moves_backward():
    mgr,client,holder=make_manager(safe_state(push_encoder=8000.0)); arm(mgr)
    client.writes.clear()

    import threading
    def plc_feedback():
        for value in (7950.0, 7900.0, 7850.0, 7810.0):
            time.sleep(0.04)
            holder['state'] = safe_state(push_encoder=value)
            holder['t'] = time.monotonic()
    threading.Thread(target=plc_feedback, daemon=True).start()

    result = mgr.execute_auto_target('push', 7800.0, 2.0)
    assert result['status'] == 'reached'
    # 真机映射：push backward 速度为负；历史写入中应出现负值。
    speed_writes = [
        struct.unpack('>f', data)[0]
        for db, offset, data in client.writes
        if db == 401 and offset == 22 and len(data) == 4
    ]
    assert any(v < 0 for v in speed_writes)
    assert speed_writes[-1] == pytest.approx(0.0)
    mgr.disarm()


def test_execute_auto_target_stops_if_feedback_moves_away():
    mgr,client,holder=make_manager(safe_state(push_encoder=8000.0)); arm(mgr)

    import threading
    def plc_feedback():
        # 目标 7000，却持续向上走，必须自动停。
        for value in (8050.0, 8100.0, 8200.0, 8300.0, 8400.0):
            time.sleep(0.035)
            holder['state'] = safe_state(push_encoder=value)
            holder['t'] = time.monotonic()
    threading.Thread(target=plc_feedback, daemon=True).start()

    with pytest.raises(RuntimeError, match='远离目标'):
        mgr.execute_auto_target('push', 7000.0, 2.0)
    assert struct.unpack('>f', bytes(client.dbs[401][22:26]))[0] == pytest.approx(0.0)
    mgr.disarm()


def test_execute_auto_target_swing_stops_at_angle():
    mgr,client,holder=make_manager(safe_state(swing_angle=3.0)); arm(mgr)

    import threading
    def plc_feedback():
        for value in (20.0, 45.0, 70.0, 89.4):
            time.sleep(0.04)
            holder['state'] = safe_state(swing_angle=value)
            holder['t'] = time.monotonic()
    threading.Thread(target=plc_feedback, daemon=True).start()

    result = mgr.execute_auto_target('swing', 90.0, 2.0)
    assert result['status'] == 'reached'
    assert struct.unpack('>f', bytes(client.dbs[401][26:30]))[0] == pytest.approx(0.0)
    mgr.disarm()


def test_execute_auto_target_cancel_stops_axis():
    mgr,client,holder=make_manager(safe_state(lift_encoder=7000.0)); arm(mgr)

    import threading
    outcome = {}
    def run():
        try:
            outcome['result'] = mgr.execute_auto_target('lift', 9000.0, 2.0)
        except Exception as exc:
            outcome['error'] = str(exc)
    t = threading.Thread(target=run)
    t.start()
    time.sleep(0.08)
    cancel = mgr.cancel_auto_target('lift')
    t.join(timeout=1.0)

    assert cancel['cancelled'] is True
    assert '取消' in outcome.get('error', '')
    assert struct.unpack('>f', bytes(client.dbs[401][18:22]))[0] == pytest.approx(0.0)
    mgr.disarm()


def test_execute_auto_target_is_rejected_when_axis_limit_blocks_direction():
    mgr,_,_=make_manager(
        safe_state(lift_encoder=5000.0, lift_limit_triggered=True)
    )
    arm(mgr)
    # safe_state 的限位方向配置由工程配置决定；只验证会经过定向限位检查。
    blocked = mgr._blocked_limit_direction('lift')
    target = 4000.0 if blocked == 'up' else 6000.0
    with pytest.raises(RuntimeError, match='限位'):
        mgr.execute_auto_target('lift', target, 2.0)
    mgr.disarm()


def test_execute_auto_target_has_stricter_auto_speed_limit():
    mgr,_,_=make_manager(safe_state(push_encoder=8000.0)); arm(mgr)
    with pytest.raises(RuntimeError, match='最多允许'):
        mgr.execute_auto_target('push', 7000.0, 6.0)
    mgr.disarm()


def test_rectifier_command_latch_allows_power_ready_before_plc_feedback():
    state = safe_state(
        communication_ok=True,
        fault=False,
        rectifier_indicator=False,
        dig_mode=True,
        lift_right_release_indicator=True,
        push_left_release_indicator=True,
        rotation_release_indicator=True,
    )
    mgr,client,_=make_manager(state); arm(mgr)
    mgr.pulse('rectifier_start')
    assert mgr._rectifier_command_latched is True
    mgr._require_power_ready(state)
    mgr.disarm()


def test_rectifier_stop_clears_command_latch():
    state = safe_state(
        communication_ok=True,
        fault=False,
        rectifier_indicator=False,
        dig_mode=True,
    )
    mgr,client,_=make_manager(state); arm(mgr)
    mgr.pulse('rectifier_start')
    assert mgr._rectifier_command_latched is True
    mgr.pulse('rectifier_stop')
    assert mgr._rectifier_command_latched is False
    mgr.disarm()


def test_fault_reset_pulses_both_db401_and_comm_db():
    mgr,client,_=make_manager(safe_state(communication_ok=False, fault=True)); arm(mgr)
    client.writes.clear()
    mgr.pulse('fault_reset_button')
    assert (client.dbs.setdefault(28, bytearray(256))[100] & (1 << 5)) == 0
    assert any(db == 28 and offset == 100 for db, offset, _ in client.writes)
    assert any(db == 401 and offset == 1 for db, offset, _ in client.writes)
    mgr.disarm()


def test_brake_release_uses_comm_db_direct_remote_bit():
    state = safe_state(
        communication_ok=False, fault=False, rectifier_indicator=True,
        dig_mode=True, lift_right_release_indicator=True
    )
    mgr,client,_=make_manager(state); arm(mgr)
    client.writes.clear()
    result = mgr.pulse('lift_right_release_brake_open')
    assert result['kind'] == 'LIVE_BRAKE_RELEASE_CONFIRMED'
    assert (client.dbs.setdefault(28, bytearray(256))[101] & (1 << 4)) == 0
    assert any(db == 28 and offset == 101 for db, offset, _ in client.writes)
    mgr.disarm()


def test_brake_close_uses_comm_db_direct_remote_bit():
    mgr,client,_=make_manager(); arm(mgr)
    client.writes.clear()
    mgr.pulse('push_left_valve_close')
    assert (client.dbs.setdefault(28, bytearray(256))[102] & (1 << 3)) == 0
    assert any(db == 28 and offset == 102 for db, offset, _ in client.writes)
    mgr.disarm()


def test_motion_no_longer_blocked_only_by_communication_ok_false():
    state = safe_state(
        communication_ok=False, fault=False, rectifier_indicator=True,
        dig_mode=True, lift_right_release_indicator=True
    )
    mgr,client,_=make_manager(state); arm(mgr)
    mgr.jog_start('lift','up',1.0)
    mgr.jog_stop('lift')
    mgr.disarm()


def test_comm_remote_authority_bit_is_held_for_remote_control():
    mgr,client,_=make_manager(safe_state(remote_mode=True)); arm(mgr)
    mgr._ensure_comm_remote_authority()
    assert (client.dbs.setdefault(28, bytearray(256))[101] & 0x01) != 0
    assert (client.dbs.setdefault(28, bytearray(256))[100] & (1 << 7)) == 0
    mgr.disarm()


def test_reset_establishes_remote_authority_before_fr_reset():
    mgr,client,_=make_manager(safe_state(
        remote_mode=True, communication_ok=False, fault=True,
        rectifier_indicator=True
    )); arm(mgr)
    client.writes.clear()
    mgr.pulse('fault_reset_button')
    assert any(db == 28 and offset == 101 for db, offset, _ in client.writes)
    assert any(db == 28 and offset == 100 for db, offset, _ in client.writes)
    mgr.disarm()


def test_brake_release_establishes_remote_authority():
    state = safe_state(
        remote_mode=True, communication_ok=False, fault=False,
        rectifier_indicator=True, dig_mode=True,
        lift_right_release_indicator=True
    )
    mgr,client,_=make_manager(state); arm(mgr)
    client.writes.clear()
    mgr.pulse('lift_right_release_brake_open')
    assert any(db == 28 and offset == 101 for db, offset, _ in client.writes)
    mgr.disarm()


def test_walk_mode_stops_brakes_then_holds_mode_until_feedback():
    state = safe_state(
        remote_mode=True, local_mode=False,
        communication_ok=False, fault=False,
        dig_mode=True, propel_mode=False,
        lift_right_release_indicator=False,
        push_left_release_indicator=False,
        rotation_release_indicator=False,
    )
    mgr,client,holder=make_manager(state); arm(mgr)
    client.writes.clear()

    import threading
    def plc_feedback():
        time.sleep(0.12)
        holder['state'] = safe_state(
            remote_mode=True, local_mode=False,
            communication_ok=False, fault=False,
            dig_mode=False, propel_mode=True,
            lift_right_release_indicator=False,
            push_left_release_indicator=False,
            rotation_release_indicator=False,
        )
        holder['t'] = time.monotonic()
    threading.Thread(target=plc_feedback, daemon=True).start()

    result = mgr.pulse('walk_mode_button')
    assert result['kind'] == 'LIVE_MODE_SWITCH_CONFIRMED'
    assert result['mode'] == '行走'
    assert any(db == 28 and offset == 101 for db, offset, _ in client.writes)
    assert any(db == 401 for db, offset, _ in client.writes)
    assert any(db == 28 and offset == 102 for db, offset, _ in client.writes)
    mgr.disarm()


def test_dig_mode_stops_brakes_then_holds_mode_until_feedback():
    state = safe_state(
        remote_mode=True, local_mode=False,
        communication_ok=False, fault=False,
        dig_mode=False, propel_mode=True,
        lift_right_release_indicator=False,
        push_left_release_indicator=False,
        rotation_release_indicator=False,
    )
    mgr,client,holder=make_manager(state); arm(mgr)
    client.writes.clear()

    import threading
    def plc_feedback():
        time.sleep(0.12)
        holder['state'] = safe_state(
            remote_mode=True, local_mode=False,
            communication_ok=False, fault=False,
            dig_mode=True, propel_mode=False,
            lift_right_release_indicator=False,
            push_left_release_indicator=False,
            rotation_release_indicator=False,
        )
        holder['t'] = time.monotonic()
    threading.Thread(target=plc_feedback, daemon=True).start()

    result = mgr.pulse('dig_mode_button')
    assert result['kind'] == 'LIVE_MODE_SWITCH_CONFIRMED'
    assert result['mode'] == '挖掘'
    assert any(db == 28 and offset == 101 for db, offset, _ in client.writes)
    assert any(db == 401 for db, offset, _ in client.writes)
    mgr.disarm()
