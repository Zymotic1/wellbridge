"""
Shared FastAPI dependency functions used across routers.
"""

from fastapi import Request
from agent.graph import compile_graph


def get_agent_graph(request: Request):
    """Return the pre-compiled LangGraph graph from app state."""
    return request.app.state.agent_graph
