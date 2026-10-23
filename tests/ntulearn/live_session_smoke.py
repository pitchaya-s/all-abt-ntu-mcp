"""Opt-in NTULearn live reads. Save credentials locally with auth save; prints only counts/statuses."""

import asyncio
from pathlib import Path
import tempfile

from mcp import Client

from ntulearn import mcp_server
from stars.mcp_server import mcp


async def main():
    session = mcp_server.session
    try:
        async with Client(mcp) as client:
            async def call(name, **arguments):
                reply = await client.call_tool(name, arguments)
                if reply.is_error:
                    raise RuntimeError(reply.content[0].text)
                return reply.structured_content
            courses = await call("ntulearn_list_courses", limit=100)
            assert courses["courses"]
            print("Live enrolled courses/organizations:", len(courses["courses"]), flush=True)
            cached = await call("ntulearn_list_courses", limit=100)
            assert cached["from_cache"] and cached["retrieved_at"] == courses["retrieved_at"]
            print("Live cache reuse verified.", flush=True)
            selected = [c for c in courses["courses"] if c["available"] == "Yes" and c["organization"] is False]
            assert selected, "No available enrolled course for content smoke checks."
            course_id = selected[-1]["id"]
            contents = await call("ntulearn_get_course_contents", course_id=course_id)
            print("Live root content items:", len(contents["contents"]), flush=True)
            announcements = await call("ntulearn_get_announcements", course_id=course_id)
            print("Live announcements:", len(announcements["announcements"]), flush=True)
            gradebook = await call("ntulearn_get_gradebook", course_id=course_id)
            print("Live gradebook columns/grades:", len(gradebook["columns"]), len(gradebook["grades"]), flush=True)
            calendar = await call("ntulearn_get_calendar")
            print("Live calendar items:", len(calendar["items"]), flush=True)
            file_checked = False
            queue = [(item, 0) for item in contents["contents"]]
            visits = 0
            with tempfile.TemporaryDirectory() as directory:
                while queue and visits < 15 and not file_checked:
                    item, depth = queue.pop(0)
                    if item["has_children"] and depth < 3:
                        children = await call("ntulearn_get_course_contents", course_id=course_id, parent_id=item["id"])
                        visits += 1
                        queue.extend((child, depth + 1) for child in children["contents"])
                    elif "file" in (item["type"] or "").lower():
                        attachments = await call("ntulearn_get_content_attachments", course_id=course_id, content_id=item["id"])
                        visits += 1
                        if attachments["attachments"]:
                            attachment = attachments["attachments"][0]
                            download = await call("ntulearn_download_file", course_id=course_id, content_id=item["id"], attachment_id=attachment["id"],
                                                  destination=str(Path(directory) / "attachment.bin"))
                            assert Path(download["path"]).stat().st_size == download["bytes_written"] > 0
                            file_checked = True
                            print("Live attachment list and temporary file download verified; bytes:", download["bytes_written"], flush=True)
                if not file_checked:
                    print("Live file download not verified: no attachment found within the bounded sample.", flush=True)
            previous = session.status().last_verified_at
            session.run(session._context.clear_cookies)
            refreshed = await call("ntulearn_list_courses", limit=100, refresh=True)
            assert not refreshed["from_cache"]
            assert session.status().last_verified_at > previous
            assert [c["id"] for c in refreshed["courses"]] == [c["id"] for c in courses["courses"]]
            print("Live cookie expiry followed by automatic fresh login verified.", flush=True)
    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(main())
