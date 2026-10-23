from shared.sitefinity import link, page_data, text
from .models import Location, ServiceError


def locations(body, page):
    data = page_data(body, page, 12)
    rows = [Location(name=text(item["title"]), address=text(item.get("location")),
                     phone=text(item.get("phone")), fax=text(item.get("fax")), email=text(item.get("email")),
                     operating_hours=text(item.get("operatingHours")), map_url=link(item.get("mapUrl")))
            for item in data["items"]]
    if len({(item.name, item.address) for item in rows}) != len(rows):
        raise ServiceError("NTU returned duplicate locations; no complete directory was inferred.")
    return rows, data["totalItems"], data["totalPages"]
