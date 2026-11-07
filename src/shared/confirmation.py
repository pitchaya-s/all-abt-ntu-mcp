"""Ask the MCP host to confirm actions with external or local side effects."""

import inspect
import json
from functools import partial, wraps
from typing import Annotated, get_type_hints

import anyio
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.resolve import Elicit, Resolve
from pydantic import BaseModel, StrictBool


class Confirmation(BaseModel):
    confirm: StrictBool


def confirmed_tool(function, name):
    """Require host confirmation without exposing a confirmation argument to the model."""
    signature = inspect.signature(function)
    confirmation_name = "confirmation_result"
    if confirmation_name in signature.parameters:
        raise ValueError("Confirmation result conflicts with tool arguments")

    def ask(**arguments) -> Elicit[Confirmation]:
        details = json.dumps(arguments, default=str, ensure_ascii=True)
        return Elicit(
            f"Confirm this action: {name}\nArguments: {details}", Confirmation
        )

    ask.__signature__ = signature.replace(return_annotation=Elicit[Confirmation])
    ask.__annotations__ = {
        **get_type_hints(function, include_extras=True),
        "return": Elicit[Confirmation],
    }
    confirmation_type = Annotated[Confirmation, Resolve(ask)]

    @wraps(function)
    async def guarded(*args, **kwargs):
        confirmation = kwargs.pop(confirmation_name)
        if confirmation.confirm is not True:
            raise ToolError("The action was not confirmed; nothing was changed.")
        if inspect.iscoroutinefunction(function):
            return await function(*args, **kwargs)
        return await anyio.to_thread.run_sync(partial(function, *args, **kwargs))

    guarded.__annotations__ = {
        **get_type_hints(function, include_extras=True),
        confirmation_name: confirmation_type,
    }
    guarded.__signature__ = signature.replace(
        parameters=[
            *signature.parameters.values(),
            inspect.Parameter(
                confirmation_name,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=confirmation_type,
            ),
        ]
    )
    return guarded
