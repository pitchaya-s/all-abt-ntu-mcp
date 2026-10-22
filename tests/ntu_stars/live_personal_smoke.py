"""Live personal WISH tools over stdio MCP. Prints statuses and counts only."""

import asyncio
import os
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters

ROOT = Path(__file__).resolve().parents[2]


async def main() -> None:
    async with Client(StdioServerParameters(
        command="uvx",
        args=["--no-cache", "--from", str(ROOT), "--with", "playwright>=1.50,<2", "all-abt-ntu-mcp"],
        env={key: os.environ[key] for key in ("NTU_USERNAME", "NTU_PASSWORD", "NTU_PERSONAL_CACHE_TTL_SECONDS") if key in os.environ},
        cwd=str(ROOT),
    )) as client:
        listing = await client.list_tools()
        assert {"stars_auth_status", "stars_get_stars_planner", "stars_get_degree_audit"} <= {t.name for t in listing.tools}
        status = await client.call_tool("stars_auth_status", {})
        assert not status.is_error and status.structured_content["credentials_configured"], "Configure NTU_USERNAME and NTU_PASSWORD first."
        planner, audit = await asyncio.gather(
            client.call_tool("stars_get_stars_planner", {"refresh": True}),
            client.call_tool("stars_get_degree_audit", {}),
        )
        if planner.is_error:
            raise RuntimeError("Live Planner MCP lookup failed; inspect the tool error locally.")
        data = planner.structured_content
        assert not data["from_cache"]
        assert [p["plan_number"] for p in data["saved_plans"]] == [1, 2, 3]
        for plan in data["saved_plans"]:
            if plan["status"] == "loaded":
                assert plan["timetable_status"] in {"parsed", "empty"}, "Saved-plan timetable needs parser review."
                assert not plan["unparsed_sessions"], "Saved-plan cells were not fully parsed."
            print(f"Plan {plan['plan_number']}: {plan['status']}; {len(plan['courses'])} course(s), {len(plan['sessions'])} session(s).")
        print(f"Registered courses: {data['registered_courses_status']}; AY{data['academic_year']} semester {data['semester']}.")
        cached = await client.call_tool("stars_get_stars_planner", {})
        assert not cached.is_error
        if status.structured_content["personal_cache_ttl_seconds"]:
            assert cached.structured_content["from_cache"]
        if audit.is_error:
            raise RuntimeError("Live Degree Audit MCP lookup failed; inspect the tool error locally.")
        print("Degree Audit: parsed successfully.")
        refreshed = await client.call_tool("stars_get_stars_planner", {"refresh": True})
        assert not refreshed.is_error and not refreshed.structured_content["from_cache"], "Planner refresh after Degree Audit failed."
        print("Live personal MCP smoke passed, including concurrent calls, caching, and refresh after Degree Audit.")


if __name__ == "__main__":
    asyncio.run(main())
