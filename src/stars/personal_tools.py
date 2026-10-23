"""Local authenticated STARS tools; never registered by the hosted server."""

from typing import Annotated, Literal, cast

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from .compact import personal_fields, saved_plan_fields
from .client import NTURequestError
from .wish import (
    AuthStatus, DegreeAuditResult, SavePlanResult, StarsPlannerResult,
    get_degree_audit as fetch_degree_audit,
    get_stars_planner as fetch_stars_planner,
    ntu_auth_status as fetch_ntu_auth_status,
    save_stars_plan as persist_stars_plan,
)


class PlannedIndex(BaseModel):
    course_code: str = Field(description="NTU undergraduate course code")
    index: str = Field(pattern=r"^[0-9]{1,12}$", description="Index number as a string")


def ntu_auth_status() -> AuthStatus:
    """Report whether WISH credentials are configured and whether this process has verified a session."""
    return fetch_ntu_auth_status()


def get_stars_planner(refresh: bool = False) -> StarsPlannerResult:
    """Get registered courses, the published term, and saved Plans 1–3 with indexes and timetables. Use refresh after editing a plan."""
    try:
        return cast(StarsPlannerResult, personal_fields(fetch_stars_planner(refresh=refresh)))
    except (NTURequestError, ValueError) as error:
        raise ToolError(str(error)) from error


def save_stars_plan(
    plan_number: Literal[1, 2, 3],
    courses: Annotated[list[PlannedIndex], Field(min_length=1, max_length=13)],
    academic_year: int,
    semester: Literal[1, 2],
) -> SavePlanResult:
    """Replace saved Plan 1, 2, or 3 with the complete supplied course/index list for the current Planner term. Omitted courses are removed from that plan. Verifies persistence by loading the saved plan. Does not perform course registration, dropping, or index swapping."""
    try:
        result = persist_stars_plan(plan_number, [course.model_dump() for course in courses], academic_year, semester)
        return {**result, "saved_plan": saved_plan_fields(result["saved_plan"])}
    except (NTURequestError, ValueError) as error:
        raise ToolError(str(error)) from error


def get_degree_audit() -> DegreeAuditResult:
    """Get your degree requirements, examination results, and registered courses from Degree Audit."""
    try:
        return cast(DegreeAuditResult, personal_fields(fetch_degree_audit()))
    except (NTURequestError, ValueError) as error:
        raise ToolError(str(error)) from error


def register_tools(mcp: MCPServer) -> None:
    read = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)
    mcp.tool(name="stars_auth_status", annotations=read)(ntu_auth_status)
    mcp.tool(name="stars_get_stars_planner", annotations=read)(get_stars_planner)
    mcp.tool(name="stars_get_degree_audit", annotations=read)(get_degree_audit)
    mcp.tool(name="stars_save_stars_plan", annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True,
    ))(save_stars_plan)
