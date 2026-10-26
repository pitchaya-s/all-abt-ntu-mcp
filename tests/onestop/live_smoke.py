"""Opt-in authenticated reads; prints statuses, never account records or cookies."""

import asyncio
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from jsonschema import Draft202012Validator
from mcp import Client
from mcp.client.stdio import StdioServerParameters


async def main():
    env = {key: os.environ[key] for key in ("DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR") if key in os.environ}
    params = StdioServerParameters(command=sys.executable, args=["-c", "from shared.cli import main; main()"], env=env)
    async with Client(params) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools if t.name.startswith("onestop_")}
        assert len(tools) == 59
        for tool in tools.values():
            Draft202012Validator.check_schema(tool.input_schema)
            Draft202012Validator.check_schema(tool.output_schema)

        async def call(name, **arguments):
            result = await client.call_tool(name, arguments)
            if result.is_error:
                raise RuntimeError(name + ": " + " ".join(c.text for c in result.content if hasattr(c, "text")))
            try:
                Draft202012Validator(tools[name].output_schema).validate(result.structured_content)
            except Exception:
                raise RuntimeError(name + ": output schema mismatch") from None
            print(name + ": OK", flush=True)
            return result.structured_content

        status = await call("onestop_auth_status")
        assert status["credentials_configured"] is True, "An unlocked native keyring and saved student account are required."
        categories = await call("onestop_list_catalog_categories")
        assert categories["categories"]
        await call("onestop_list_catalog_items", query="letter")
        category = next(c for c in categories["categories"] if "Certificates" in c["title"])
        items = await call("onestop_list_catalog_items", category_id=category["category_id"])
        form = next(i for i in items["items"] if i["form_item_id"])
        details = await call("onestop_get_catalog_item", item_id=form["form_item_id"])
        assert details["fields"]
        assert all(set(f) == {"name", "label", "type", "mandatory", "read_only", "choices"} for f in details["fields"])
        knowledge = await call("onestop_search_knowledge", query="VPN")
        article = next(a for a in knowledge["articles"] if "VPN" in a["title"])
        content = await call("onestop_get_knowledge_article", article_id=article["article_id"])
        assert content["text"]
        requests = await call("onestop_list_my_requests")
        supported = next((r for r in requests["requests"] if r["detail_supported"]), None)
        if supported:
            await call("onestop_get_my_request", request_id=supported["request_id"])
            await call("onestop_get_request_activity", request_id=supported["request_id"])
            await call("onestop_list_attachments", target={"kind": "request", "request_id": supported["request_id"]})
        else:
            print("onestop_get_my_request: SKIPPED (no supported record in current lists)", flush=True)
        cached = await call("onestop_get_knowledge_article", article_id=article["article_id"])
        assert cached["cached"]
        assert (await call("onestop_auth_status"))["session_verified"]
        for name in ("get_dashboard", "list_announcements", "list_my_actions", "list_popular_links", "get_profile",
                     "get_cart", "list_favourites", "list_my_appointments"):
            await call("onestop_" + name)
        services = await call("onestop_list_payment_services", query="*Library")
        if services["records"]:
            await call("onestop_get_payment_service", service_id=services["records"][0]["record_id"])
        await call("onestop_get_article_feedback", article_id=article["article_id"])
        await call("onestop_list_article_comments", article_id=article["article_id"])
        await call("onestop_list_attachments", target={"kind": "article", "article_id": article["article_id"]})
        draft = await call("onestop_prepare_request", item_id=form["form_item_id"])
        try:
            await call("onestop_get_request_draft", draft_id=draft["draft_id"])
            await call("onestop_update_request_draft", draft_id=draft["draft_id"], values={})
            await call("onestop_list_attachments", target={"kind": "draft", "draft_id": draft["draft_id"]})
        finally:
            await call("onestop_discard_request_draft", draft_id=draft["draft_id"])
        # Public native booking form; selecting a window only changes the local draft.
        appointment = await call("onestop_prepare_request", item_id="7d4c7ceedb68d4108672324d7c9619f5")
        try:
            await call("onestop_get_appointment_configuration", draft_id=appointment["draft_id"])
            await call("onestop_search_form_references", draft_id=appointment["draft_id"], field_name="reason", query="*")
            day = (datetime.now(ZoneInfo("Asia/Singapore")) + timedelta(days=1)).date().isoformat()
            slots = await call("onestop_get_appointment_slots", draft_id=appointment["draft_id"], date=day)
            if slots["slots"]:
                await call("onestop_select_appointment_slot", draft_id=appointment["draft_id"], slot_id=slots["slots"][0]["slot_id"])
        finally:
            await call("onestop_discard_request_draft", draft_id=appointment["draft_id"])


if __name__ == "__main__":
    asyncio.run(main())
