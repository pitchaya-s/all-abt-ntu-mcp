"""Read-only course search integration; run with uv run python tests/live_search_smoke.py."""

import asyncio
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters


ROOT = Path(__file__).resolve().parents[1]


async def main():
    async with Client(StdioServerParameters(
        command="uvx", args=["--no-cache", "--from", str(ROOT), "ntu-stars-mcp"], cwd=str(ROOT),
    )) as client:
        for query, year, mode, expected in [
            ("SC20", 2026, "full_time", 6),
            ("DATA STRUCTURES", 2026, "full_time", 3),
            ("SC20", 2025, "full_time", 6),
            ("SC20", 2026, "part_time", 4),
            ("ZZZXQ99999", 2026, "full_time", 0),
        ]:
            args = {"query": query, "academic_year": year, "semester": 1 if year == 2026 else 2, "study_mode": mode, "limit": 2}
            reply = await client.call_tool("search_courses", args)
            assert not reply.is_error, reply.content
            found = reply.structured_content
            assert found["total_count"] == expected, found
            assert found["has_more"] == (expected > 2)
            codes = [course["course_code"] for course in found["courses"]]
            for offset in range(2, expected, 2):
                page = await client.call_tool("search_courses", {**args, "offset": offset})
                assert not page.is_error, page.content
                assert page.structured_content["retrieved_at"] == found["retrieved_at"]
                codes.extend(course["course_code"] for course in page.structured_content["courses"])
            assert len(set(codes)) == expected
            if query == "DATA STRUCTURES":
                assert codes == ["IE2108", "SC1007", "SC1303"], codes
            print(f"Live MCP course search passed: {query}, AY{year}, {mode}, {expected} courses.")
        details = await client.call_tool("get_course_metadata", {"course_code": "SC2001", "academic_year": 2026, "semester": 1})
        assert not details.is_error, details.content
        assert details.structured_content["course_name"] == "ALGORITHM DESIGN & ANALYSIS~"
        assert details.structured_content["au"] == 3.0
        print("Live MCP search metadata matches the SC2001 course lookup.")


if __name__ == "__main__":
    asyncio.run(main())
