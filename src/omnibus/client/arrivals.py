"""Live arrival and service-status operations."""

from .. import parser
from ..models import Arrivals, OmnibusError, ServiceStatus


class ArrivalMethods:
    def get_arrivals(self, route_filter, stop_query, source):
        self._query(stop_query)
        campus_routes = ("Blue", "Brown", "Green", "Grey", "Red")
        lta_services = ("179", "179A", "199")
        if source not in {"all", "shuttle", "lta"}:
            raise OmnibusError("Choose all, shuttle, or lta arrival sources.")
        codes = list(
            campus_routes
            if source == "shuttle"
            else lta_services
            if source == "lta"
            else campus_routes + lta_services
        )
        if route_filter:
            if route_filter not in codes:
                raise OmnibusError(
                    "The selected route does not match the arrival source; choose the matching shuttle or lta source."
                )
            codes = [route_filter]
        stops, source_urls, _, _ = self._stop_records(codes)
        query = stop_query.strip().casefold()
        stops = [
            stop
            for stop in stops
            if not query
            or query in stop.name.casefold()
            or query in stop.stop_code.casefold()
        ]
        if len(stops) > 20:
            raise OmnibusError(
                "More than 20 route-stop matches. Narrow stop_query or route_filter before requesting live arrivals."
            )
        shuttle_rows, lta_rows = [], []
        for stop in stops:
            name = (
                "GetETAAndNextETA_LTA"
                if stop.is_lta_service
                else "GetETAAndNextETA_FMS"
            )
            data, url = self._post(
                name,
                "MainFlow.Shuttle",
                inputs={"BusStopCode": stop.stop_code, "RouteCode": stop.route_code},
            )
            row = parser.stop_arrival(data, stop)
            (lta_rows if stop.is_lta_service else shuttle_rows).append(row)
            source_urls.append(url)
        return Arrivals(
            retrieved_at=self._now(),
            source_urls=list(dict.fromkeys(source_urls)),
            route_filter=route_filter,
            stop_query=stop_query,
            shuttle_arrivals=shuttle_rows,
            lta_arrivals=lta_rows,
        )

    def get_service_status(self, route_code):
        schedule_data, schedule_url = self._post(
            "GetRoutesMinMax", "MainFlow.Shuttle", inputs={"RouteCode": route_code}
        )
        special_data, special_url = self._post(
            "CheckPHSpecialDay", "MainFlow.Shuttle", inputs={"RouteCode": route_code}
        )
        message_data, message_url = self._post(
            "GetTempMessages", "MainFlow.Shuttle", inputs={}
        )
        try:
            schedules = parser.schedules(schedule_data, route_code)
            result = message_data["Result"]
            if not isinstance(result, dict):
                raise TypeError
            is_local = schedule_data["IsFromLocalDB"]
            is_holiday = special_data["IsTodayPublicHoliday"]
            is_special = special_data["IsTodaySpecialDay"]
            has_message = result["IsShowTemp"]
            for value in (is_local, is_holiday, is_special, has_message):
                if type(value) is not bool:
                    raise TypeError
        except (KeyError, TypeError):
            raise OmnibusError(
                "NTU Omnibus returned an unexpected service-status response."
            ) from None
        return ServiceStatus(
            retrieved_at=self._now(),
            source_urls=[schedule_url, special_url, message_url],
            route_code=route_code,
            schedules=schedules,
            schedule_from_local_db=is_local,
            is_public_holiday=is_holiday,
            is_special_day=is_special,
            special_day_notice=parser.optional_text(
                special_data.get("SpecialDayTextVal")
            ),
            has_temporary_message=has_message,
            temporary_message=parser.optional_text(result.get("TempMessageContent")),
            no_active_bus_message=parser.optional_text(result.get("MsgNoActiveBus")),
            no_operations_message=parser.optional_text(result.get("MsgNoOperations")),
        )
