"""Live official-source and stdio MCP client smoke test; run with `uv run python tests/live_smoke.py`."""

import asyncio
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters


ROOT = Path(__file__).resolve().parents[1]


async def main() -> None:
    async with Client(
        StdioServerParameters(
            command="uvx",
            args=["--from", str(ROOT), "ntu-course-index"],
            cwd=str(ROOT),
        )
    ) as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools.tools}
        assert "get_course_indexes" in names
        for code, year, semester, expected_count in (
            ("SC2001", 2026, 1, 36),
            ("SC2207", 2026, 1, 13),
            ("MH2802", 2026, 1, 12),
            ("SC2001", 2025, 2, 6),
        ):
            result = await client.call_tool(
                "get_course_indexes",
                {"course_code": code, "academic_year": year, "semester": semester},
            )
            if result.is_error:
                raise RuntimeError(result.content)
            data = result.structured_content
            assert data["course_code"] == code
            assert data["index_count"] == expected_count, (code, data["index_count"])
            print(
                f"Live MCP smoke passed: {data['course_code']} {data['course_name']}; "
                f"{data['index_count']} indexes from AY{data['academic_year']} semester {data['semester']}."
            )

        schedule = await client.call_tool(
            "get_index_schedule",
            {"course_code": "SC2001", "index": "10143", "academic_year": 2026, "semester": 1},
        )
        if schedule.is_error:
            raise RuntimeError(schedule.content)
        sessions = schedule.structured_content["sessions"]
        tutorial = next(item for item in sessions if item["lesson_type"] == "TUT")
        assert tutorial["day"] == "TUE" and tutorial["start_time"] == "16:30"
        print("Live MCP smoke passed: SC2001 index 10143 includes its Tuesday tutorial and all four sessions.")

        comparison = await client.call_tool(
            "compare_indexes",
            {
                "course_code": "SC2001",
                "indexes": ["10143", "10144"],
                "academic_year": 2026,
                "semester": 1,
            },
        )
        if comparison.is_error:
            raise RuntimeError(comparison.content)
        assert len(comparison.structured_content["common_sessions"]) == 2
        print("Live MCP smoke passed: SC2001 indexes 10143 and 10144 share both lecture sessions.")

        matches = await client.call_tool(
            "find_matching_indexes",
            {
                "course_code": "SC2001",
                "academic_year": 2026,
                "semester": 1,
                "constraints": {
                    "avoid_days": ["FRI"],
                    "require_sessions": [
                        {"lesson_type": "TUT", "day": "TUE", "starts_at_or_after": "16:00"}
                    ],
                },
            },
        )
        if matches.is_error:
            raise RuntimeError(matches.content)
        assert "10143" in {item["index"] for item in matches.structured_content["matches"]}
        print("Live MCP smoke passed: matching rules find SC2001 index 10143.")


if __name__ == "__main__":
    asyncio.run(main())
