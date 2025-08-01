"""
Router Agent with LangGraph State Management
[EMOJI], [EMOJI] [EMOJI], [EMOJI] [EMOJI] [EMOJI] fallback, 3[EMOJI] [EMOJI] [EMOJI] H2H [EMOJI]
"""

from typing import Dict, List, Any, Optional, TypedDict, Literal
from langgraph.graph import StateGraph, END
from datetime import datetime
import logging
from .router_agent import RouterAgent
from ..common.handlers import HANDLERS
from ..common.memory_store_sqlite import add_message, get_messages

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# [EMOJI] [EMOJI]
class RouterState(TypedDict):
    """[EMOJI] [EMOJI] [EMOJI]"""
    session_id: str
    query: str
    try_count: int
    max_tries: int
    agent: Optional[str]
    stage: Literal["initial", "classify", "fallback", "h2h", "execute", "complete", "error"]
    agent_result: Optional[Dict[str, Any]]
    user_selection_needed: bool
    available_agents: List[str]
    conversation_history: List[Dict[str, str]]
    error_message: Optional[str]

class RouterGraphAgent:
    """LangGraph [EMOJI] [EMOJI] [EMOJI]"""
    
    def __init__(self):
        self.router = RouterAgent()
        self.graph = self._create_graph()
        
    def _create_graph(self):
        """LangGraph [EMOJI] [EMOJI] [EMOJI]"""
        workflow = StateGraph(RouterState)
        
        # [EMOJI] [EMOJI]
        workflow.add_node("initialize", self._initialize_node)
        workflow.add_node("classify", self._classify_node)
        workflow.add_node("fallback", self._fallback_node)
        workflow.add_node("h2h", self._h2h_node)
        workflow.add_node("execute", self._execute_node)
        workflow.add_node("complete", self._complete_node)
        
        # [EMOJI] [EMOJI]
        workflow.set_entry_point("initialize")
        
        # [EMOJI] [EMOJI]
        workflow.add_conditional_edges(
            "initialize",
            lambda x: "classify" if x["stage"] == "classify" else "error",
            {
                "classify": "classify",
                "error": "complete"
            }
        )
        
        workflow.add_conditional_edges(
            "classify",
            self._classify_router,
            {
                "execute": "execute",
                "fallback": "fallback",
                "h2h": "h2h"
            }
        )
        
        workflow.add_conditional_edges(
            "fallback",
            lambda x: "h2h" if x["try_count"] >= x["max_tries"] else "complete",
            {
                "h2h": "h2h",
                "complete": "complete"
            }
        )
        
        workflow.add_edge("h2h", "complete")
        workflow.add_edge("execute", "complete")
        workflow.add_edge("complete", END)
        
        return workflow.compile()
    
    async def _initialize_node(self, state: RouterState) -> RouterState:
        """[EMOJI] [EMOJI]"""
        logger.info(f"[Initialize] Session: {state['session_id']}, Query: {state['query']}")
        
        # [EMOJI] [EMOJI] [EMOJI]
        try:
            messages = get_messages(state["session_id"])
            state["conversation_history"] = [
                {"role": msg[0], "content": msg[1]} 
                for msg in messages[-10:]  # [EMOJI] 10[EMOJI]
            ]
        except Exception as e:
            logger.warning(f"Failed to load conversation history: {e}")
            state["conversation_history"] = []
        
        state["stage"] = "classify"
        state["try_count"] = 0
        state["max_tries"] = 3
        state["available_agents"] = list(HANDLERS.keys())
        
        return state
    
    async def _classify_node(self, state: RouterState) -> RouterState:
        """[EMOJI] [EMOJI]"""
        state["try_count"] += 1
        logger.info(f"[Classify] Try {state['try_count']}/{state['max_tries']}")
        
        # RouterAgent[EMOJI] [EMOJI] [EMOJI]
        agent_id = await self.router.classify(state["query"])
        
        if agent_id and agent_id in HANDLERS:
            state["agent"] = agent_id
            state["stage"] = "execute"
            logger.info(f"[Classify] Success: {agent_id}")
        else:
            state["stage"] = "fallback"
            logger.warning(f"[Classify] Failed (try {state['try_count']})")
            
        return state
    
    def _classify_router(self, state: RouterState) -> str:
        """[EMOJI] [EMOJI] [EMOJI] [EMOJI]"""
        if state["stage"] == "execute":
            return "execute"
        elif state["try_count"] >= state["max_tries"]:
            return "h2h"
        else:
            return "fallback"
    
    async def _fallback_node(self, state: RouterState) -> RouterState:
        """Fallback [EMOJI] - [EMOJI] [EMOJI] [EMOJI]"""
        logger.info(f"[Fallback] User selection needed")
        
        state["user_selection_needed"] = True
        state["error_message"] = f"[EMOJI] [EMOJI] [EMOJI] ({state['try_count']}/{state['max_tries']}[EMOJI] [EMOJI])"
        
        return state
    
    async def _h2h_node(self, state: RouterState) -> RouterState:
        """Human-to-Human [EMOJI] - 3[EMOJI] [EMOJI] [EMOJI]"""
        logger.warning(f"[H2H] Entering H2H mode after {state['max_tries']} failures")
        
        state["stage"] = "h2h"
        state["user_selection_needed"] = True
        state["error_message"] = "[EMOJI] [EMOJI] [EMOJI] [EMOJI] [EMOJI] [EMOJI] [EMOJI]."
        
        return state
    
    async def _execute_node(self, state: RouterState) -> RouterState:
        """[EMOJI] [EMOJI] - [EMOJI] [EMOJI] [EMOJI]"""
        agent_id = state["agent"]
        logger.info(f"[Execute] Running agent: {agent_id}")
        
        try:
            handler = HANDLERS[agent_id]
            result = await handler({
                "query": state["query"],
                "session_id": state["session_id"]
            })
            
            state["agent_result"] = result
            state["stage"] = "complete"
            
            # [EMOJI] [EMOJI]
            await add_message(
                state["session_id"], 
                "assistant", 
                result.get("response", ""),
                metadata={"agent": agent_id}
            )
            
        except Exception as e:
            logger.error(f"[Execute] Error: {e}")
            state["error_message"] = str(e)
            state["stage"] = "error"
            
        return state
    
    async def _complete_node(self, state: RouterState) -> RouterState:
        """[EMOJI] [EMOJI]"""
        logger.info(f"[Complete] Stage: {state['stage']}")
        return state
    
    async def process(self, session_id: str, query: str) -> Dict[str, Any]:
        """[EMOJI] [EMOJI]"""
        initial_state = RouterState(
            session_id=session_id,
            query=query,
            try_count=0,
            max_tries=3,
            agent=None,
            stage="initial",
            agent_result=None,
            user_selection_needed=False,
            available_agents=[],
            conversation_history=[],
            error_message=None
        )
        
        # [EMOJI] [EMOJI]
        final_state = await self.graph.ainvoke(initial_state)
        
        # [EMOJI] [EMOJI]
        if final_state["stage"] == "complete" and final_state["agent_result"]:
            return final_state["agent_result"]
        elif final_state["user_selection_needed"]:
            return {
                "success": False,
                "user_selection_needed": True,
                "available_agents": final_state["available_agents"],
                "response": final_state["error_message"] or "[EMOJI] [EMOJI].",
                "try_count": final_state["try_count"],
                "stage": final_state["stage"]
            }
        else:
            return {
                "success": False,
                "response": final_state["error_message"] or "[EMOJI] [EMOJI] [EMOJI] [EMOJI].",
                "stage": final_state["stage"]
            }

# [EMOJI] [EMOJI]
router_graph = RouterGraphAgent()