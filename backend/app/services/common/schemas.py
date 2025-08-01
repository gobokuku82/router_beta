# common/schemas.py
from typing import TypedDict, Literal, Optional, List, Dict, Any
from langchain_core.messages import HumanMessage

# [EMOJI]
# 1) [EMOJI] [EMOJI] [EMOJI] [EMOJI] [EMOJI]
class BaseState(TypedDict):
    query: str
    session_id: str

# [EMOJI]
# 2) Router [EMOJI] [EMOJI]
class RouterState(BaseState, total=False):
    try_count: int
    agent: Optional[str]
    stage: Literal[
        "initial", "classified", "fallback",
        "h2h_wait", "completed", "error"
    ]
    agent_result: Optional[Dict[str, Any]]
    user_selection_needed: bool
    available_agents: Optional[List[str]]

# [EMOJI]
# 3) [EMOJI] [EMOJI] [EMOJI](docs_agent) [EMOJI] [EMOJI]
class DocState(BaseState, total=False):
    # [EMOJI] [EMOJI]
    messages: List[HumanMessage]

    # [EMOJI] [EMOJI]
    doc_type: Optional[str]
    template_content: Optional[str]
    filled_data: Optional[dict]
    violation: Optional[str]
    final_doc: Optional[str]

    # [EMOJI]·[EMOJI] [EMOJI]
    retry_count: int
    restart_classification: Optional[bool]
    classification_retry_count: Optional[int]
    end_process: Optional[bool]
    parse_retry_count: Optional[int]
    parse_failed: Optional[bool]
