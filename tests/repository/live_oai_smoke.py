"""Opt-in, bounded OAI-PMH stdio checks; prints no harvested metadata."""

import asyncio
import sys

from jsonschema import Draft202012Validator
from mcp import Client
from mcp.client.stdio import StdioServerParameters


async def main():
    params = StdioServerParameters(command=sys.executable, args=["-c", "from shared.cli import main; main()"])
    async with Client(params, cache=None) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        async def call(name, **arguments):
            result = await client.call_tool(name, arguments)
            assert not result.is_error, name
            Draft202012Validator(tools[name].output_schema).validate(result.structured_content)
            print(name + ": OK", flush=True)
            return result.structured_content

        info = await call("drntu_oai_identify")
        assert info["protocol_version"] == "2.0"
        formats = await call("drntu_oai_list_metadata_formats")
        assert "oai_dc" in {value["metadata_prefix"] for value in formats["formats"]}
        sets = await call("drntu_oai_list_sets", limit=50)
        assert sets["sets"]
        if sets["pagination"]["next_offset"] is not None:
            sets = await call("drntu_oai_list_sets", limit=50, offset=sets["pagination"]["next_offset"])
        token = sets["pagination"]["resumption_token"]
        assert token, "Published set-page structure changed; inspect pagination before continuing."
        more_sets = await call("drntu_oai_list_sets", resumption_token=token, limit=1)
        assert more_sets["sets"]

        filters = dict(from_date="2026-01-01", until_date="2026-01-02", limit=2)
        first = await call("drntu_oai_list_records", **filters)
        assert first["records"] and first["pagination"]["next_offset"] is not None
        second = await call("drntu_oai_list_records", **filters, offset=first["pagination"]["next_offset"])
        assert not {row["identifier"] for row in first["records"]}.intersection(row["identifier"] for row in second["records"])
        headers = await call("drntu_oai_list_records", **filters, headers_only=True)
        assert [row["identifier"] for row in headers["records"]] == [row["identifier"] for row in first["records"]]
        assert all(row["metadata"] is None for row in headers["records"])
        stamp = first["records"][0]["datestamp"]
        exact = await call("drntu_oai_list_records", from_date=stamp, until_date=stamp, limit=2)
        assert exact["records"] and all(row["datestamp"] == stamp for row in exact["records"])
        identifier = first["records"][0]["identifier"]
        detail = await call("drntu_oai_get_record", identifier=identifier)
        assert detail["record"]["metadata"] == first["records"][0]["metadata"]
        available = await call("drntu_oai_list_metadata_formats", identifier=identifier)
        if "qdc" in {value["metadata_prefix"] for value in available["formats"]}:
            qdc = await call("drntu_oai_get_record", identifier=identifier, metadata_prefix="qdc")
            assert qdc["record"]["metadata_xml"]
        empty = await call("drntu_oai_list_records", from_date="1900-01-01", until_date="1900-01-02")
        assert empty["records"] == []
        invalid = await client.call_tool("drntu_oai_list_records", {"resumption_token": "invalid-token-for-smoke-check"})
        assert invalid.is_error and "badResumptionToken" in invalid.content[0].text
        print("OAI invalid-token error: OK", flush=True)
        print("OAI-PMH live smoke passed; no research files downloaded or metadata saved.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
