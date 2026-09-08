import logging
from .models import Emergency, EmergencyStatus

log = logging.getLogger(__name__)
ORDER = list(EmergencyStatus)

def transition(emergency: Emergency, incoming: EmergencyStatus) -> bool:
    if emergency.status in {EmergencyStatus.COMPLETED, EmergencyStatus.FAILED}:
        return False
    if incoming == EmergencyStatus.FAILED:
        emergency.status = incoming
        return True
    if ORDER.index(incoming) < ORDER.index(emergency.status):
        log.warning("Rejected stale transition %s -> %s for %s", emergency.status, incoming, emergency.id)
        return False
    emergency.status = incoming
    return True