"""Public app paths and metadata patterns for the Omnibus client."""

import re

_ORIGIN = "https://apps.ntu.edu.sg"
_BASE = _ORIGIN + "/NTUOmnibus/"
_ALLOWED_HOSTS = frozenset({"apps.ntu.edu.sg"})
_ROUTE_CODES = ("Blue", "Brown", "Green", "Grey", "Red", "179", "179A", "199")
_STOP_CACHE_TTL_SECONDS = 300
_MAX_RESPONSE_BYTES = 8_000_000
_MAX_REDIRECTS = 5
_MAX_ATTEMPTS = 2
_MAX_RETRY_DELAY_SECONDS = 10.0
_RETRYABLE = {429, 500, 502, 503, 504}
_REDIRECTS = {301, 302, 303, 307, 308}
_ASSETS = (
    "/NTUOmnibus/scripts/CampusShuttle_MUI.controller.js",
    "/NTUOmnibus/scripts/CampusShuttle_MUI.MainFlow.RenderMap.mvc.js",
)
_CALL_PATTERN = re.compile(
    r"(callDataAction|callServerAction|callAggregateWithStartIndexAndClientVars)"
    r'\("([^"]+)",\s*"([^"]+)",\s*"([^"]+)"'
)
_ROUTE_COLORS = (
    "{'data':[{'route_code':'Blue','color_code':'0054A6','Order':'2'},"
    "{'route_code':'Green','color_code':'007C48','Order':'3'},"
    "{'route_code':'Brown','color_code':'866D4B','Order':'4'},"
    "{'route_code':'Red','color_code':'D71440','Order':'1'},"
    "{'route_code':'179','color_code':'944496','Order':'5'},"
    "{'route_code':'179A','color_code':'944496','Order':'6'},"
    "{'route_code':'199','color_code':'944496','Order':'7'},"
    "{'route_code':'default','color_code':'181C62','Order':'8'}]}"
)
_SGH_ROUTE_COLORS = (
    "{'data':[{'route_code':'Carpark H','color_code':'0054A6','Order':'2'},"
    "{'route_code':'Carpark H (Night)','color_code':'32BCAD','Order':'4'},"
    "{'route_code':'SGH-Blue','color_code':'866D4B','Order':'1'},"
    "{'route_code':'SGH-Orange','color_code':'D71440','Order':'3'}]}"
)
