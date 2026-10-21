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
            args=["--no-cache", "--from", str(ROOT), "ntu-stars-mcp"],
            cwd=str(ROOT),
        )
    ) as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools.tools}
        assert "get_course_indexes" in names
        assert "get_index" in names and "get_index_schedule" not in names
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
            assert data["vacancy_metadata"]["status"] in {"term_mismatch", "closed", "unavailable"}, data["vacancy_metadata"]
            assert all(index["vacancies_available"] is None and index["waitlist_length"] is None for index in data["indexes"])
            if code == "SC2001" and year == 2026 and semester == 1:
                metadata = await client.call_tool("get_course_metadata", {"course_code": code, "academic_year": year, "semester": semester})
                assert not metadata.is_error
                assert metadata.structured_content["course_description_status"] == "available"
                assert "algorithm design and analysis" in metadata.structured_content["course_description"].lower()
            print(
                f"Live MCP smoke passed: {data['course_code']}; "
                f"{data['index_count']} indexes from AY{data['academic_year']} semester {data['semester']}."
            )

        schedule = await client.call_tool(
            "get_index",
            {"course_code": "SC2001", "index": "10143", "academic_year": 2026, "semester": 1},
        )
        if schedule.is_error:
            raise RuntimeError(schedule.content)
        sessions = schedule.structured_content["sessions"]
        tutorial = next(item for item in sessions if item["lesson_type"] == "TUT")
        assert tutorial["day"] == "TUE" and tutorial["start_time"] == "16:30"
        print("Live MCP smoke passed: SC2001 index 10143 includes its Tuesday tutorial and all four sessions.")

        for code in ["SC2001", "SC2207"]:
            args = {"course_code": code, "academic_year": 2026, "semester": 2}
            result = await client.call_tool("get_course_indexes", args)
            assert not result.is_error, result.content
            data = result.structured_content
            status = data["vacancy_metadata"]["status"]
            assert status in {"available", "closed"}, data["vacancy_metadata"]
            for index in data["indexes"]:
                assert index["vacancy_status"] == status, index
                for field in ["vacancies_available", "waitlist_length"]:
                    value = index[field]
                    assert value is None if status == "closed" else isinstance(value, int) and value >= 0
            selected = data["indexes"][0]
            result = await client.call_tool("get_index", {**args, "index": selected["index"]})
            assert not result.is_error, result.content
            one_index = result.structured_content
            for field in ["vacancy_status", "vacancies_available", "waitlist_length", "sessions"]:
                assert one_index[field] == selected[field]
            if status == "available":
                assert one_index["vacancy_metadata"]["retrieved_at"]
                assert one_index["vacancy_metadata"]["from_cache"]
            print(f"Live MCP vacancy smoke passed: {code}, {len(data['indexes'])} indexes, vacancy status {status}.")

        graduate = await client.call_tool("get_graduate_course_schedule", {"course_code": "EE6102"})
        if graduate.is_error:
            raise RuntimeError(graduate.content)
        graduate_data = graduate.structured_content
        assert graduate_data["course_code"] == "EE6102"
        assert graduate_data["class_groups"]
        assert set(graduate_data) == {
            "course_code", "course_name", "au", "academic_year", "term", "schedule_complete", "class_groups", "source_url"
        }
        graduate_sessions = [session for group in graduate_data["class_groups"] for session in group["sessions"]]
        assert any(session["day"] == "FRI" and session["start_time"] == "18:30" for session in graduate_sessions)
        print(
            f"Live MCP smoke passed: graduate EE6102 AY{graduate_data['academic_year']} term "
            f"{graduate_data['term']}, {len(graduate_data['class_groups'])} class group(s)."
        )

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
