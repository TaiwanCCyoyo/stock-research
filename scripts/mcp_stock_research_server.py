from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

try:
    from stock_research_query import (
        QueryError,
    )
    from stock_research_query import (
        inspect_task_trade as inspect_trade,
    )
    from stock_research_query import (
        list_research_tasks as list_tasks,
    )
    from stock_research_query import (
        list_task_trades as list_trades,
    )
except ModuleNotFoundError:
    from scripts.stock_research_query import (
        QueryError,
    )
    from scripts.stock_research_query import (
        inspect_task_trade as inspect_trade,
    )
    from scripts.stock_research_query import (
        list_research_tasks as list_tasks,
    )
    from scripts.stock_research_query import (
        list_task_trades as list_trades,
    )


mcp = FastMCP("stock-research-query")


def tool_result(payload: dict[str, Any]) -> dict[str, Any]:
    return payload


def as_tool_error(exc: QueryError) -> ToolError:
    return ToolError(str(exc))


@mcp.tool()
def inspect_task_trade(
    task: str,
    code: str | None = None,
    date: str | None = None,
    action: str = "BUY",
    occurrence: int = 0,
    trade_id: str | None = None,
    data_path: str | None = None,
) -> dict[str, Any]:
    """Return structured evidence for one task trade."""
    try:
        return tool_result(
            inspect_trade(
                task=task,
                code=code,
                date=date,
                action=action,
                occurrence=occurrence,
                trade_id=trade_id,
                data_path=data_path,
            )
        )
    except QueryError as exc:
        raise as_tool_error(exc) from exc


@mcp.tool()
def list_task_trades(
    task: str,
    code: str | None = None,
    action: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Return compact task trades with stable trade ids and signal reasons."""
    try:
        return tool_result(list_trades(task=task, code=code, action=action, limit=limit))
    except QueryError as exc:
        raise as_tool_error(exc) from exc


@mcp.tool()
def list_research_tasks(limit: int = 20) -> dict[str, Any]:
    """Return local research tasks and available analysis artifacts."""
    return tool_result(list_tasks(limit=limit))


if __name__ == "__main__":
    mcp.run(transport="stdio")
