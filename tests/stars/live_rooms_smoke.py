"""Opt-in public room-tool checks; prints statuses/counts, never saves timetables."""

import argparse
import asyncio
import sys

from jsonschema import Draft202012Validator
from mcp import Client
from mcp.client.stdio import StdioServerParameters


async def main(args):
    params = StdioServerParameters(command=sys.executable, args=["-c", "from shared.cli import main; main()"])
    async with Client(params) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}

        async def call(name, arguments):
            result = await client.call_tool(name, arguments)
            assert not result.is_error, result
            Draft202012Validator(tools[name].output_schema).validate(result.structured_content)
            print(name + ": OK", flush=True)
            return result.structured_content

        term = dict(
            academic_year=args.academic_year, semester=int(args.semester) if args.semester != "S" else "S"
        )
        window = dict(
            day=args.day, start_time=args.start_time, end_time=args.end_time, teaching_weeks=args.week
        )
        found = await call("stars_find_available_rooms", {**term, "window": window, "limit": 5})
        assert found["coverage"]["index_count"] > 0
        print(
            "Observed rooms:",
            found["coverage"]["observed_room_count"],
            "Matches:",
            found["match_count"],
            flush=True,
        )
        if found["rooms"]:
            venue = found["rooms"][0]["venue"]
            schedule = await call("stars_get_room_schedule", {**term, "venue": venue, "limit": 100})
            assert schedule["session_count"] > 0 and schedule["cached"]
            empty = await call("stars_get_room_schedule", {**term, "venue": venue, **window, "limit": 100})
            assert empty["session_count"] == 0
        else:
            print("Room detail skipped: no matches in the requested window.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--academic-year", required=True, type=int)
    parser.add_argument("--semester", required=True, choices=["1", "2", "S"])
    parser.add_argument("--day", required=True, choices=["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"])
    parser.add_argument("--start-time", required=True)
    parser.add_argument("--end-time", required=True)
    parser.add_argument(
        "--week",
        action="append",
        type=int,
        help="Teaching week, repeat for multiple weeks; omit for whole-term checks.",
    )
    asyncio.run(main(parser.parse_args()))
