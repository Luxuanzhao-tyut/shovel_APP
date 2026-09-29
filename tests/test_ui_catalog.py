from ui.control_catalog import COMMANDS, DIG_DIRECTION, WALK_DIRECTION, SPEED_COMMANDS
from ui.control_facade import ControlFacade


def test_ui_catalog_maps_to_variable_map():
    facade=ControlFacade(); names={item.name for item in COMMANDS}; assert names; assert names<=set(facade.mapping)
    assert all(facade.mapping[name]['direction']=='write' for name in names)


def test_shared_walk_and_dig_channels_are_explicit():
    assert DIG_DIRECTION['lift_up']==WALK_DIRECTION['right_forward']
    assert DIG_DIRECTION['push_forward']==WALK_DIRECTION['left_forward']
    assert SPEED_COMMANDS['lift']==SPEED_COMMANDS['right_track']
    assert SPEED_COMMANDS['push']==SPEED_COMMANDS['left_track']


def test_tia_confirmed_tail_commands_have_known_addresses_and_preview_when_unarmed():
    facade=ControlFacade()
    for name in ('rotation_right','bucket_open_command','horn_command','lift_right_auto_start','push_left_auto_start','rotation_auto_start'):
        assert facade.mapping[name]['valid_address'] is True
        plan=facade.preview(name,True); assert plan['written'] is False and plan['address_known'] is True


def test_facade_starts_unarmed_and_config_is_fail_closed():
    facade=ControlFacade(); assert facade.armed is False
    assert facade.config['safety']['write_enabled'] is False and facade.config['safety']['dry_run'] is True
