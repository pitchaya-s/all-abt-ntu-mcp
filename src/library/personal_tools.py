"""Local authenticated library tools; never registered by the hosted server."""

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from .mcp_server import Day, FacilityID, _call
from .models import FacilitySchedule
from .session import FacilitySession


session = FacilitySession()
INSTRUCTIONS = (
    "library_get_facility_schedule requires the shared local keyring credentials and Chromium. "
    "It reads daily available/unavailable time grids and preserves source status classes. Missing slots are unknown. "
    "Booking identities and checksums are omitted. MFA or CAPTCHA stops login; no bookings are submitted. "
)


def get_facility_schedule(
    date: Day,
    space_id: FacilityID | None = None,
    location_id: FacilityID | None = None,
    group_id: FacilityID | None = None,
    refresh: bool = False,
) -> FacilitySchedule:
    """Read a day's LibFacilities room/seat time grid, room description and source status classes. Supply space_id, or both location_id and group_id, from facility/map results. Requires saved local NTU student credentials and Chromium. Reuses an in-memory session and caches for 60 seconds. MFA/CAPTCHA returns an error; no booking, cart, checkout, loan, or hold is submitted. Missing slots are unknown, not free."""
    return _call(session.get_schedule, date, space_id, location_id, group_id, refresh)



def register_tools(mcp: MCPServer) -> None:
    mcp.tool(name="library_get_facility_schedule", annotations=ToolAnnotations(
        readOnlyHint=True, idempotentHint=True, openWorldHint=True,
    ))(get_facility_schedule)
