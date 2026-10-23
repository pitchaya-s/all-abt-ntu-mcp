"""Normalize DSpace HAL responses without guessing missing metadata."""

from uuid import UUID
from urllib.parse import parse_qs, urlsplit

from ..models import MetadataValue, RepositoryError
from .client import API
from .models import Checksum, Container, File, ItemSummary, Page, SearchFilter


def identifier(value):
    return str(UUID(value))


def records(value):
    if not isinstance(value, list) or any(not isinstance(v, dict) for v in value):
        raise RepositoryError("DR-NTU returned an unexpected collection format.")
    return value


def embedded(data, key):
    block = data.get("_embedded", {})
    if key in block:
        return records(block[key])
    if data.get("page", {}).get("totalElements") == 0:
        return []
    raise RepositoryError("DR-NTU returned an incomplete HAL response; no records were inferred.")


def pagination(data, count, requested_page, requested_size):
    page = data["page"]
    number, size = page["number"], page["size"]
    total, pages = page.get("totalElements"), page.get("totalPages")
    if number != requested_page or size != requested_size or count > size:
        raise RepositoryError("DR-NTU returned mismatched pagination; no complete page was inferred.")
    if total is not None and count != min(size, max(0, total - number * size)):
        raise RepositoryError("DR-NTU returned an incomplete result page.")
    if pages is not None:
        next_page = number + 1 if number + 1 < pages else None
    else:
        next_page = number + 1 if data.get("_links", {}).get("next") else None
    return Page(page=number, page_size=size, total_elements=total, total_pages=pages, next_page=next_page)


def metadata(data):
    raw = data["metadata"]
    if not isinstance(raw, dict):
        raise RepositoryError("DR-NTU returned invalid item metadata.")
    return {key: [MetadataValue(value=v["value"], language=v.get("language")) for v in records(values)]
            for key, values in raw.items()}


def values(meta, *keys):
    return [v.value for key in keys for v in meta.get(key, [])]


def summary(data):
    if data.get("type") != "item":
        raise RepositoryError("DR-NTU returned a non-item search result.")
    meta = metadata(data)
    item_id = identifier(data["uuid"])
    return ItemSummary(
        item_id=item_id, title=data["name"], entity_type=data.get("entityType"),
        authors=values(meta, "dc.contributor.author", "dc.creator"),
        dates_issued=values(meta, "dc.date.issued"),
        identifiers=values(meta, "dc.identifier.doi", "dc.identifier.uri"),
        rights=values(meta, "datacite.rights", "dc.rights", "dc.rights.uri"),
        url=f"https://dr.ntu.edu.sg/entities/publication/{item_id}" if data.get("entityType") == "Publication"
        else f"https://dr.ntu.edu.sg/items/{item_id}",
    )


def container(data):
    if data.get("type") not in ("community", "collection"):
        raise RepositoryError("DR-NTU returned an unexpected container type.")
    meta = metadata(data)
    container_id = identifier(data["uuid"])
    count = data.get("archivedItemsCount")
    kind = "communities" if data["type"] == "community" else "collections"
    return Container(container_id=container_id, name=data["name"], description=values(meta, "dc.description.abstract"),
                     archived_items_count=count if count is not None and count >= 0 else None,
                     url=f"https://dr.ntu.edu.sg/{kind}/{container_id}")


def facet_filter(data, name):
    link = data.get("_links", {}).get("search", {}).get("href")
    if link is None:
        return None
    url = urlsplit(link)
    if url.scheme != "https" or url.netloc != "dr.ntu.edu.sg" or url.path != "/server/api/discover/search/objects":
        raise RepositoryError("DR-NTU returned an unexpected facet search link.")
    candidates = parse_qs(url.query).get("f." + name, [])
    if not candidates:
        return None
    value, operator = candidates[-1].rsplit(",", 1)
    return SearchFilter(field=name, value=value, operator=operator)


def file(data):
    if data.get("type") != "bitstream":
        raise RepositoryError("DR-NTU returned a non-file record.")
    file_id = identifier(data["uuid"])
    checksum = data.get("checkSum")
    content_url = data.get("_links", {}).get("content", {}).get("href")
    if content_url is not None and content_url != f"{API}/core/bitstreams/{file_id}/content":
        raise RepositoryError("DR-NTU returned an unexpected file-content URL.")
    return File(file_id=file_id, name=data["name"], bundle_name=data.get("bundleName"), size_bytes=data.get("sizeBytes"),
                checksum=Checksum(algorithm=checksum["checkSumAlgorithm"], value=checksum["value"]) if checksum else None,
                rights=values(metadata(data), "datacite.rights", "dc.rights", "dc.rights.uri"), content_url=content_url)
