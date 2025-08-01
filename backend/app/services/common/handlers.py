from ..employee_agent import run as employee_run
from ..client_agent import run as client_run
from ..search_agent.run import run as search_run
from ..docs_agent import run as doc_run

HANDLERS = {
    "employee_agent": employee_run,
    "client_agent": client_run,
    "search_agent": search_run,
    "docs_agent": doc_run,
}

# task_router에서 사용하는 이름으로 export
agent_handlers = HANDLERS
