"""Opt-in public catalogue checks; no licensed files or account data are fetched."""

import asyncio
import argparse
from datetime import datetime, timedelta
import os
import sys
from zoneinfo import ZoneInfo

from mcp import Client
from mcp.client.stdio import StdioServerParameters
from jsonschema import Draft202012Validator


async def main(personal=False):
    env = {
        key: os.environ[key]
        for key in ("DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR")
        if personal and key in os.environ
    }
    params = StdioServerParameters(
        command=sys.executable, args=["-c", "from shared.cli import main; main()"], env=env
    )
    async with Client(params) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}

        async def call(name, **arguments):
            result = await client.call_tool(name, arguments)
            assert not result.is_error, result
            Draft202012Validator(tools[name].output_schema).validate(result.structured_content)
            print(name + ": OK", flush=True)
            return result.structured_content

        first = await call("library_search", query="algorithms", limit=2)
        second = await call("library_search", query="algorithms", limit=2, offset=first["next_offset"])
        assert first["records"] and second["records"]
        assert not {r["record_id"] for r in first["records"]}.intersection(
            r["record_id"] for r in second["records"]
        )
        local = next(r for r in first["records"] if r["context"] == "L")
        detail = await call("library_get_record", record_id=local["record_id"], context=local["context"])
        assert detail["record"]["record_id"] == local["record_id"]
        articles = await call("library_search", query="machine learning", resource_type="articles", limit=3)
        central = next(r for r in articles["records"] if r["context"] == "PC")
        detail = await call("library_get_record", record_id=central["record_id"], context=central["context"])
        assert detail["record"]["record_id"] == central["record_id"]
        isbn = await call("library_search", query="9780262046305", field="isbn", match="exact", limit=1)
        assert isbn["records"]
        await call("library_get_availability", record_id=local["record_id"], context=local["context"])
        directory = await call("library_list_facilities")
        day = (datetime.now(ZoneInfo("Asia/Singapore")) + timedelta(days=1)).date().isoformat()
        floor = next(v for v in directory["facilities"] if v["map_slug"])
        availability = await call(
            "library_get_map_availability", map_slug=floor["map_slug"], date=day, time="14:00"
        )
        assert availability["spaces"]
        if personal:
            room = next(v for v in directory["facilities"] if v["space_id"])
            schedule = await call("library_get_facility_schedule", date=day, space_id=room["space_id"])
            assert schedule["spaces"] and all(v["name"] for v in schedule["spaces"])
            cached = await call("library_get_facility_schedule", date=day, space_id=room["space_id"])
            assert cached["cached"]
            group = next(v for v in directory["facilities"] if v["location_id"] and v["group_id"])
            await call(
                "library_get_facility_schedule",
                date=day,
                location_id=group["location_id"],
                group_id=group["group_id"],
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--personal", action="store_true")
    asyncio.run(main(parser.parse_args().personal))
