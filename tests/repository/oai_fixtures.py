"""Synthetic OAI-PMH responses; no copied NTU research records or contacts."""

from datetime import datetime, timezone
from html import escape
from urllib.parse import parse_qs, urlsplit


IDENTIFIER = "oai:dr.ntu.edu.sg:10356/EXAMPLE1"
DELETED = "oai:dr.ntu.edu.sg:10356/EXAMPLE-DELETED"
TOKEN = "next +/page=1 & extra"
STAMP = "2026-10-23T08:00:00Z"


def envelope(verb, content="", error=None):
    payload = f'<error code="{error}">Synthetic protocol error</error>' if error else f'<{verb}>{content}</{verb}>'
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/">
<responseDate>{STAMP}</responseDate><request verb="{verb}">https://dr.ntu.edu.sg/server/oai/request</request>{payload}</OAI-PMH>'''.encode()


def header(identifier=IDENTIFIER, deleted=False):
    status = ' status="deleted"' if deleted else ''
    return f'<header{status}><identifier>{escape(identifier)}</identifier><datestamp>{STAMP}</datestamp><setSpec>col_example</setSpec></header>'


def record(identifier=IDENTIFIER, deleted=False, prefix="oai_dc"):
    if deleted:
        return '<record>' + header(identifier, True) + '</record>'
    metadata = '<oai_dc:dc><dc:title xml:lang="en">Synthetic research &amp; methods</dc:title><dc:creator>Example, Author</dc:creator><dc:creator>Example, Coauthor</dc:creator><dc:rights>restricted</dc:rights><dc:description>Untrusted source text</dc:description></oai_dc:dc>'
    if prefix != "oai_dc":
        metadata = '<q:qualifieddc xmlns:q="http://dspace.org/qualifieddc/"><dc:title>Synthetic research</dc:title><q:extra code="retained"><q:nested>value</q:nested></q:extra></q:qualifieddc>'
    return '<record>' + header(identifier) + '<metadata>' + metadata + '</metadata><about><extra xmlns="urn:example:provenance">retained</extra></about></record>'


def fake_get(url, refresh=False):
    parameters = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
    verb = parameters['verb']
    token = parameters.get('resumptionToken')
    if token and token != TOKEN:
        body = envelope(verb, error='badResumptionToken')
    elif verb == 'Identify':
        body = envelope(verb, '<repositoryName>Synthetic NTU repository</repositoryName><baseURL>https://dr.ntu.edu.sg/server/oai/request</baseURL><protocolVersion>2.0</protocolVersion><adminEmail>repository@example.invalid</adminEmail><earliestDatestamp>2008-05-15T02:56:52Z</earliestDatestamp><deletedRecord>transient</deletedRecord><granularity>YYYY-MM-DDThh:mm:ssZ</granularity><description><custom xmlns="urn:example:repository">retained</custom></description>')
    elif verb == 'ListMetadataFormats':
        body = envelope(verb, ''.join(f'<metadataFormat><metadataPrefix>{prefix}</metadataPrefix><schema>https://example.invalid/{prefix}.xsd</schema><metadataNamespace>urn:example:{prefix}</metadataNamespace></metadataFormat>' for prefix in ('oai_dc', 'qdc')))
    elif verb == 'ListSets':
        content = ''.join(f'<set><setSpec>col_example{number}</setSpec><setName>Synthetic collection {number}</setName><setDescription><details xmlns="urn:example:set">retained</details></setDescription></set>' for number in ([4] if token else [1, 2, 3]))
        continuation = '' if token else escape(TOKEN)
        body = envelope(verb, content + f'<resumptionToken cursor="{3 if token else 0}" completeListSize="4" expirationDate="2099-01-01T00:00:00Z">{continuation}</resumptionToken>')
    elif verb in ('ListRecords', 'ListIdentifiers'):
        if parameters.get('from') == '1900-01-01':
            body = envelope(verb, error='noRecordsMatch')
        else:
            rows = [(IDENTIFIER, False)] if token else [(IDENTIFIER, False), (DELETED, True), ('oai:dr.ntu.edu.sg:10356/EXAMPLE3', False)]
            content = ''.join(header(identifier, deleted) if verb == 'ListIdentifiers' else record(identifier, deleted, parameters.get('metadataPrefix', 'oai_dc')) for identifier, deleted in rows)
            body = envelope(verb, content + f'<resumptionToken cursor="{3 if token else 0}" completeListSize="4">{escape(TOKEN) if not token else ""}</resumptionToken>')
    elif verb == 'GetRecord':
        identifier = parameters['identifier']
        body = envelope(verb, record(identifier, identifier == DELETED, parameters['metadataPrefix']))
    else:
        raise AssertionError(verb)
    return body, dict(retrieved_at=datetime(2026, 10, 23, 8, tzinfo=timezone.utc), source_url=url, cached=False)
