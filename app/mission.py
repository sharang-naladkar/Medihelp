import logging
from pymavlink import mavutil

log = logging.getLogger(__name__)
MAV_FRAME_GLOBAL_RELATIVE_ALT_INT = 6

def generate_mission(home_lat: float, home_lng: float, target_lat: float, target_lng: float, altitude_m: float = 40.0) -> list[dict]:
    """MISSION_ITEM_INT upload sequence: home waypoint, target waypoint, RTL."""
    if not 30 <= altitude_m <= 50:
        raise ValueError("altitude_m must be between 30 and 50 metres AGL")
    points = [(home_lat, home_lng, 0.0), (target_lat, target_lng, altitude_m), (home_lat, home_lng, 0.0)]
    commands = [mavutil.mavlink.MAV_CMD_NAV_WAYPOINT, mavutil.mavlink.MAV_CMD_NAV_WAYPOINT, mavutil.mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH]
    items = []
    for seq, ((lat, lng, alt), command) in enumerate(zip(points, commands)):
        message = mavutil.mavlink.MAVLink_mission_item_int_message(1, 1, seq, MAV_FRAME_GLOBAL_RELATIVE_ALT_INT, command, int(seq == 0), 1, 0, 0, 0, 0, int(lat * 1e7), int(lng * 1e7), alt, 0)
        raw = {field: getattr(message, field) for field in message.fieldnames}
        raw["message_type"] = "MISSION_ITEM_INT"
        items.append(raw)
    log.info("Generated raw MAVLink mission items: %s", items)
    return items