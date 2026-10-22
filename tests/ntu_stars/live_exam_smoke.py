"""Live public undergraduate exam lookup via stdio MCP; run with `uv run python tests/ntu_stars/live_exam_smoke.py`."""

import asyncio
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters


ROOT = Path(__file__).resolve().parents[2]


async def main() -> None:
    async with Client(
        StdioServerParameters(
            command="uvx",
            args=["--no-cache", "--from", str(ROOT), "all-abt-ntu-mcp"],
            cwd=str(ROOT),
        )
    ) as client:
        tools = await client.list_tools()
        assert "get_undergraduate_exam_schedule" in {tool.name for tool in tools.tools}
        result = await client.call_tool("get_undergraduate_exam_schedule", {"course_code": "SC2001"})
        if result.is_error:
            raise RuntimeError(result.content)
        data = result.structured_content
        assert data["course_code"] == "SC2001"
        assert data["exam_status"] == "available", data
        assert data["exams"] and data["exams"][0]["date"]
        print(
            f"Live MCP exam smoke passed: SC2001 AY{data['academic_year']} semester {data['semester']}; "
            f"{data['exam_count']} exam(s), first on {data['exams'][0]['date']} at "
            f"{data['exams'][0]['start_time']} for {data['exams'][0]['duration_minutes']} minutes."
        )


if __name__ == "__main__":
    asyncio.run(main())
