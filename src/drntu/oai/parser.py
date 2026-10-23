"""Strict OAI-PMH envelopes, Dublin Core fields and preserved metadata XML."""

from datetime import date, datetime
import re
import xml.etree.ElementTree as ET

from ..models import MetadataValue, RepositoryError
from .models import OAIPagination, OAIRecord


NS = "{http://www.openarchives.org/OAI/2.0/}"
DC = "{http://purl.org/dc/elements/1.1/}"
DC_ROOT = "{http://www.openarchives.org/OAI/2.0/oai_dc/}dc"
LANG = "{http://www.w3.org/XML/1998/namespace}lang"


class _NoDTD(ET.TreeBuilder):
    def doctype(self, name, pubid, system):
        raise RepositoryError("OAI-PMH XML contained a DTD; retrieval stopped without resolving entities.")


def datestamp(value):
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        date.fromisoformat(value)
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("Use YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ for OAI datestamps.")
    return value


def required(element, name):
    values = element.findall(NS + name)
    if len(values) != 1 or not (values[0].text or "").strip():
        raise RepositoryError("DR-NTU returned incomplete OAI-PMH metadata; no records were inferred.")
    return values[0].text.strip()


def xml(element):
    return ET.tostring(element, encoding="unicode").strip()


def envelope(body, verb):
    try:
        root = ET.fromstring(body, parser=ET.XMLParser(target=_NoDTD()))
        pending = [(root, 0)]
        count = 0
        while pending:
            node, depth = pending.pop()
            count += 1
            if depth > 64 or count > 100000:
                raise RepositoryError("OAI-PMH XML exceeded the nesting or element limit.")
            pending.extend((child, depth + 1) for child in node)
        if root.tag != NS + "OAI-PMH":
            raise ValueError
        response_date = datestamp(required(root, "responseDate"))
        if not response_date.endswith("Z"):
            raise ValueError
        requests = root.findall(NS + "request")
        if len(requests) != 1 or requests[0].get("verb") not in (None, verb):
            raise ValueError
        errors = root.findall(NS + "error")
        containers = root.findall(NS + verb)
        if errors:
            if containers:
                raise ValueError
            codes = [error.get("code") for error in errors]
            if codes == ["noRecordsMatch"] and verb in {"ListRecords", "ListIdentifiers"}:
                return ET.Element(NS + verb), response_date
            messages = {
                "badResumptionToken": "The continuation token expired or is invalid. Restart with the original filters and refresh=true.",
                "cannotDisseminateFormat": "This metadata format is unavailable; use drntu_oai_list_metadata_formats.",
                "idDoesNotExist": "The OAI identifier was not found; use an identifier returned by OAI listing, not a REST UUID.",
                "noMetadataFormats": "No metadata formats are available for this identifier.",
                "noSetHierarchy": "This endpoint does not expose OAI sets.",
                "badArgument": "NTU rejected the OAI arguments; check the format, date filters and token usage.",
                "badVerb": "NTU rejected this OAI-PMH operation.",
            }
            code = next((code for code in codes if code in messages), None)
            raise RepositoryError("OAI-PMH " + (code + ": " + messages[code] if code else "returned an unknown protocol error."))
        if len(containers) != 1:
            raise ValueError
        container = containers[0]
        child = {"ListRecords": "record", "ListIdentifiers": "header", "ListSets": "set", "ListMetadataFormats": "metadataFormat", "GetRecord": "record"}.get(verb)
        if child and not container.findall(NS + child):
            raise ValueError
        return container, response_date
    except (ET.ParseError, ValueError, TypeError, RecursionError):
        raise RepositoryError("DR-NTU returned malformed or unexpected OAI-PMH XML; no records were inferred.") from None


def pagination(container, count, limit, offset):
    if offset > count:
        raise RepositoryError("offset exceeds this OAI response page; follow next_offset before the next resumption_token.")
    tokens = container.findall(NS + "resumptionToken")
    if len(tokens) > 1:
        raise RepositoryError("DR-NTU returned multiple OAI continuation tokens.")
    token = tokens[0] if tokens else None
    continuation = token.text if token is not None and (token.text or "").strip() else None
    attributes = token.attrib if token is not None else {}
    def number(name):
        value = attributes.get(name)
        if value is None:
            return None
        if not re.fullmatch(r"[0-9]+", value):
            raise RepositoryError("DR-NTU returned an invalid OAI pagination count.")
        return int(value)
    expiration = attributes.get("expirationDate")
    if expiration is not None:
        datestamp(expiration)
        if not expiration.endswith("Z"):
            raise RepositoryError("DR-NTU returned an invalid OAI token expiration date.")
    next_offset = offset + limit if offset + limit < count else None
    return OAIPagination(offset=offset, page_count=count, next_offset=next_offset,
                         resumption_token=continuation if next_offset is None else None,
                         cursor=number("cursor"), complete_list_size=number("completeListSize"), expiration_date=expiration)


def record(element, headers_only=False):
    headers = [element] if headers_only else element.findall(NS + "header")
    if len(headers) != 1 or headers[0].get("status") not in (None, "deleted"):
        raise RepositoryError("DR-NTU returned an invalid OAI record header.")
    header = headers[0]
    set_specs = header.findall(NS + "setSpec")
    if any(not (value.text or "").strip() for value in set_specs):
        raise RepositoryError("DR-NTU returned an invalid OAI record header.")
    identifier = required(header, "identifier")
    if not identifier.startswith("oai:dr.ntu.edu.sg:"):
        raise RepositoryError("DR-NTU returned an unexpected OAI identifier.")
    stamp = datestamp(required(header, "datestamp"))
    deleted = header.get("status") == "deleted"
    metadata, metadata_xml = None, None
    wrappers = [] if headers_only else element.findall(NS + "metadata")
    if deleted and wrappers:
        raise RepositoryError("A deleted OAI record unexpectedly contained metadata.")
    if not headers_only and not deleted:
        if len(wrappers) != 1 or len(wrappers[0]) != 1:
            raise RepositoryError("An active OAI record was missing its metadata.")
        content = wrappers[0][0]
        if content.tag == DC_ROOT and all(child.tag.startswith(DC) and not len(child) and set(child.attrib) <= {LANG} for child in content):
            metadata = {}
            for child in content:
                metadata.setdefault("dc." + child.tag[len(DC):], []).append(MetadataValue(value=child.text or "", language=child.get(LANG)))
        else:
            metadata_xml = xml(content)
    return OAIRecord(identifier=identifier, datestamp=stamp,
                     set_specs=[value.text.strip() for value in set_specs],
                     deleted=deleted, metadata=metadata, metadata_xml=metadata_xml,
                     about_xml=[] if headers_only else [xml(value) for value in element.findall(NS + "about")])
