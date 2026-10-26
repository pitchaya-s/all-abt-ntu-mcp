"""Normalize NTU Omnibus screen-service responses."""

import ast
import json
import math
from datetime import datetime

from .models import (
    BusPosition,
    LtaArrival,
    OmnibusError,
    Route,
    RouteColor,
    RouteSchedule,
    ShuttleArrival,
    Stop,
)


def optional_text(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise OmnibusError("NTU Omnibus returned an invalid text field.")
    value = str(value).strip()
    return value or None


def _records(value, label):
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise OmnibusError(f"NTU Omnibus returned an unexpected {label} list.")
    return value


def _required_text(record, key, label):
    value = optional_text(record.get(key))
    if value is None:
        raise OmnibusError(f"NTU Omnibus omitted {label}; no value was inferred.")
    return value


def _number(value, label, required=False):
    if value is None or value == "" or (isinstance(value, str) and value.strip().upper() in {"-", "NA", "N/A"}):
        if required:
            raise OmnibusError(f"NTU Omnibus omitted {label}.")
        return None
    try:
        number = float(value)
        if isinstance(value, bool) or not math.isfinite(number):
            raise ValueError
        return number
    except (TypeError, ValueError):
        raise OmnibusError(f"NTU Omnibus returned an invalid {label}.") from None


def _integer(value, label):
    if value is None or value == "" or (isinstance(value, str) and value.strip().upper() in {"-", "NA", "N/A"}):
        return None
    try:
        if isinstance(value, bool) or isinstance(value, float) and not value.is_integer():
            raise ValueError
        return int(value)
    except (TypeError, ValueError):
        raise OmnibusError(f"NTU Omnibus returned an invalid {label}.") from None


def _boolean(value, label):
    if type(value) is not bool:
        raise OmnibusError(f"NTU Omnibus returned an invalid {label}.")
    return value


def _list_at(data, *keys, label):
    value = data
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            raise OmnibusError(f"NTU Omnibus returned an unexpected {label} response.")
        value = value[key]
    return _records(value, label)


def routes(data, colors_text):
    values = _list_at(data, "RouteList", "List", label="route")
    try:
        colors_data = json.loads(colors_text)
    except (TypeError, json.JSONDecodeError):
        try:
            colors_data = ast.literal_eval(colors_text)
        except (SyntaxError, ValueError, TypeError):
            raise OmnibusError("NTU Omnibus returned invalid route-color data.") from None
    if not isinstance(colors_data, dict):
        raise OmnibusError("NTU Omnibus returned invalid route-color data.")

    color_rows = _records(colors_data.get("data"), "route-color")
    route_list = [
        Route(
            route_code=_required_text(item, "Route", "route code"),
            description=optional_text(item.get("RouteDescription")),
            long_name=optional_text(item.get("RouteLongName")),
            is_lta_service=_boolean(item.get("IsSBS"), "LTA-service flag"),
        )
        for item in values
    ]
    colors = [
        RouteColor(
            route_code=_required_text(item, "route_code", "route-color code"),
            color_code=_required_text(item, "color_code", "route color"),
            display_order=_integer(item.get("Order"), "route-color order"),
        )
        for item in color_rows
    ]
    return route_list, colors


def bus_positions(data):
    try:
        result = data["Response"]["ActiveBusResult"]
        values = _records(result["Activebus"]["List"], "active-bus")
    except (KeyError, TypeError):
        raise OmnibusError("NTU Omnibus returned an unexpected active-bus response.") from None

    buses = []
    for item in values:
        load = item.get("LoadInfo") if isinstance(item.get("LoadInfo"), dict) else {}
        buses.append(
            BusPosition(
                vehicle_plate=_required_text(item, "Vehplate", "vehicle plate"),
                latitude=_number(item.get("Lat"), "bus latitude", required=True),
                longitude=_number(item.get("Lng"), "bus longitude", required=True),
                speed=_number(item.get("Speed"), "bus speed"),
                direction_degrees=_number(item.get("Direction"), "bus direction"),
                crowd_level=optional_text(load.get("CrowdLevel")),
                occupancy=optional_text(load.get("Occupancy")),
                capacity=_integer(load.get("Capacity"), "bus capacity"),
                ridership=_integer(load.get("Ridership"), "bus ridership"),
            )
        )

    timestamp = optional_text(result.get("TimeStamp"))
    source_timestamp = None
    if timestamp and not timestamp.startswith("1900-01-01"):
        try:
            source_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            raise OmnibusError("NTU Omnibus returned an invalid active-bus timestamp.") from None
    reported_count = _integer(result.get("ActiveBusCount"), "active-bus count")
    return buses, len(buses) if reported_count is None else reported_count, source_timestamp


def pickup_stops(data, route_code, is_lta):
    rows = _list_at(data, "PickupPoints", "PickupPointResult", "Pickuppoint", "List", label="pickup-stop")
    stops = {}
    for item in rows:
        code = _required_text(item, "Busstopcode", "stop code")
        stop = Stop(name=optional_text(item.get("Pickupname")) or code, stop_code=code,
                    route_code=route_code, service_id=optional_text(data.get("ServiceId")),
                    is_lta_service=is_lta, route_long_name=optional_text(item.get("LongName")))
        stops.setdefault(code, stop)
    return list(stops.values())


def stop_arrival(data, stop):
    if not isinstance(data, dict) or "ETA" not in data or "NextETA" not in data:
        raise OmnibusError("NTU Omnibus returned an unexpected stop-arrival response.")
    missing = data.get("IsETA_NotFound", False)
    if type(missing) is not bool:
        raise OmnibusError("NTU Omnibus returned an invalid arrival-availability flag.")
    eta = None if missing else optional_text(data["ETA"])
    next_eta = None if missing else optional_text(data["NextETA"])
    if stop.is_lta_service:
        return LtaArrival(service_no=stop.route_code, stop_code=stop.stop_code, stop_name=stop.name,
                          eta_minutes=eta, next_eta_minutes=next_eta)
    return ShuttleArrival(route_code=stop.route_code, stop_name=stop.name, stop_code=stop.stop_code,
                          eta=eta, next_eta=next_eta)


def schedules(data, route_code):
    try:
        values = _records(data["FMS_RouteMinMaxTime"]["List"], "route-schedule")
    except (KeyError, TypeError):
        raise OmnibusError("NTU Omnibus returned an unexpected route-schedule response.") from None
    output = []
    for item in values:
        raw = optional_text(item.get("Json"))
        if not raw:
            continue
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            raise OmnibusError("NTU Omnibus returned invalid route-schedule JSON.") from None
        rows = _list_at(decoded, "RouteMinMaxTimeResult", "RouteMinMaxTime", label="route-schedule")
        for row in rows:
            row_route = optional_text(row.get("Route"))
            if row_route is None or row_route.casefold() != route_code.casefold():
                continue
            output.append(
                RouteSchedule(
                    route_code=row_route,
                    first_bus=optional_text(row.get("FirstTime")),
                    last_bus=optional_text(row.get("LastTime")),
                    schedule_type=optional_text(row.get("ScheduleType")),
                    day_type=optional_text(row.get("DayType")),
                    display_order=_integer(row.get("DisplayOrder"), "schedule display order"),
                )
            )
    return output
