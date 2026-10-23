"""Bounded OAI-PMH reads without automatic repository-wide harvesting."""

from ..models import RepositoryError
from .models import OAIFormats, OAIIdentify, OAIMetadataFormat, OAIRecordResult, OAIRecords, OAISet, OAISets
from .parser import NS, datestamp, pagination, record, required, xml


def identify(client, refresh=False):
    data, response_date, snapshot = client.request("Identify", refresh=refresh)
    return OAIIdentify(**snapshot, response_date=response_date, repository_name=required(data, "repositoryName"),
                       base_url=required(data, "baseURL"), protocol_version=required(data, "protocolVersion"),
                       admin_emails=[value.text.strip() for value in data.findall(NS + "adminEmail") if (value.text or "").strip()],
                       earliest_datestamp=datestamp(required(data, "earliestDatestamp")),
                       deleted_record=required(data, "deletedRecord"), granularity=required(data, "granularity"),
                       descriptions_xml=[xml(value) for value in data.findall(NS + "description")])


def formats(client, identifier=None, refresh=False):
    data, response_date, snapshot = client.request("ListMetadataFormats", {"identifier": identifier} if identifier else None, refresh)
    return OAIFormats(**snapshot, response_date=response_date,
                      formats=[OAIMetadataFormat(metadata_prefix=required(value, "metadataPrefix"), schema_url=required(value, "schema"),
                                                 metadata_namespace=required(value, "metadataNamespace")) for value in data.findall(NS + "metadataFormat")])


def selection(metadata_prefix, set_spec, from_date, until_date, resumption_token):
    if resumption_token is not None:
        if any(value is not None for value in (metadata_prefix, set_spec, from_date, until_date)):
            raise RepositoryError("A resumption_token must be used alone: omit metadata_prefix, set_spec, from_date and until_date.")
        return {"resumptionToken": resumption_token}
    for value in (from_date, until_date):
        if value is not None:
            try:
                datestamp(value)
            except ValueError:
                raise RepositoryError("Invalid OAI date bound. Use a real YYYY-MM-DD date or UTC YYYY-MM-DDTHH:MM:SSZ timestamp.") from None
    if from_date and until_date and (len(from_date) != len(until_date) or from_date > until_date):
        raise RepositoryError("OAI date bounds must have the same precision, with from_date no later than until_date.")
    return {key: value for key, value in {"metadataPrefix": metadata_prefix or "oai_dc", "set": set_spec,
                                        "from": from_date, "until": until_date}.items() if value is not None}


def sets(client, resumption_token=None, limit=20, offset=0, refresh=False):
    data, response_date, snapshot = client.request("ListSets", {"resumptionToken": resumption_token} if resumption_token else None, refresh)
    values = data.findall(NS + "set")
    page = pagination(data, len(values), limit, offset)
    return OAISets(**snapshot, response_date=response_date, pagination=page,
                   sets=[OAISet(set_spec=required(value, "setSpec"), name=required(value, "setName"),
                                descriptions_xml=[xml(part) for part in value.findall(NS + "setDescription")]) for value in values[offset:offset + limit]])


def records(client, metadata_prefix=None, set_spec=None, from_date=None, until_date=None, resumption_token=None,
            headers_only=False, limit=10, offset=0, refresh=False):
    parameters = selection(metadata_prefix, set_spec, from_date, until_date, resumption_token)
    data, response_date, snapshot = client.request("ListIdentifiers" if headers_only else "ListRecords", parameters, refresh)
    values = data.findall(NS + ("header" if headers_only else "record"))
    page = pagination(data, len(values), limit, offset)
    return OAIRecords(**snapshot, response_date=response_date, headers_only=headers_only, pagination=page,
                      records=[record(value, headers_only) for value in values[offset:offset + limit]])


def get_record(client, identifier, metadata_prefix="oai_dc", refresh=False):
    data, response_date, snapshot = client.request("GetRecord", {"identifier": identifier, "metadataPrefix": metadata_prefix}, refresh)
    values = data.findall(NS + "record")
    if len(values) != 1:
        raise RepositoryError("DR-NTU returned an unexpected number of OAI records.")
    result = record(values[0])
    if result.identifier != identifier:
        raise RepositoryError("DR-NTU returned a different OAI identifier; no record was inferred.")
    return OAIRecordResult(**snapshot, response_date=response_date, metadata_prefix=metadata_prefix, record=result)
