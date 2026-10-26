"""Fictional shuttle and LTA records in the native screen-service shapes."""

import json

from omnibus.client import OmnibusClient


RESPONSES = {
    "DataActionGetRoutesList": {"RouteList": {"List": [{"Route": "Blue", "RouteDescription": "Campus loop", "IsSBS": False}]}},
    "GetRoutesCodejson": {"Json": "{'data':[{'route_code':'Blue','color_code':'0054A6','Order':'1'}]}"},
    "DataActionGetActiveBusServicesData": {"Response": {"ActiveBusResult": {
        "Activebus": {"List": [{"Vehplate": "TEST123", "Lat": "1.35", "Lng": "103.68", "Speed": "0",
                                "LoadInfo": {"Capacity": "40", "Ridership": "5", "CrowdLevel": "Low"}}]},
        "ActiveBusCount": "1", "TimeStamp": "1900-01-01T00:00:00"}}},
    "DataActionGetPickupCheckPoints": {},
    "GetETAAndNextETA_FMS": {"ETA": "3", "NextETA": "10"},
    "GetETAAndNextETA_LTA": {"ETA": "5", "NextETA": "15", "IsETA_NotFound": False},
    "GetRoutesMinMax": {"IsFromLocalDB": False, "FMS_RouteMinMaxTime": {"List": [{"Json": json.dumps({
        "RouteMinMaxTimeResult": {"RouteMinMaxTime": [{"Route": "Blue", "FirstTime": "07:00", "LastTime": "23:00"}]}})}]}},
    "CheckPHSpecialDay": {"IsTodayPublicHoliday": False, "IsTodaySpecialDay": False},
    "GetTempMessages": {"Result": {"IsShowTemp": False}},
}


class FixtureClient(OmnibusClient):
    def __init__(self):
        super().__init__()
        self.calls = []

    def _post(self, name, view_name, **kwargs):
        self.calls.append((name, view_name, kwargs))
        data = RESPONSES[name]
        if name == "DataActionGetPickupCheckPoints":
            route = kwargs["screen_variables"]["RouteId"]
            values = {"Blue": [{"Pickupname": "Example Hall", "Busstopcode": "EX1"}],
                      "179": [{"Pickupname": "Example Gate", "Busstopcode": "12345"}]}.get(route, [])
            data = {"ServiceId": "NTU", "PickupPoints": {"PickupPointResult": {"Pickuppoint": {"List": values}}}}
        return data, "https://apps.ntu.edu.sg/NTUOmnibus/screenservices/example/" + name
