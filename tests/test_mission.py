from pymavlink import mavutil
from app.mission import generate_mission
def test_known_location_mission_is_mission_item_int_sequence():
    items = generate_mission(18.5204, 73.8567, 18.5314, 73.8446, 40.0)
    assert [item["seq"] for item in items] == [0, 1, 2]
    assert all(item["message_type"] == "MISSION_ITEM_INT" for item in items)
    assert items[0]["command"] == mavutil.mavlink.MAV_CMD_NAV_WAYPOINT
    assert items[1]["x"] == 185314000 and items[1]["y"] == 738446000
    assert items[2]["command"] == mavutil.mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH