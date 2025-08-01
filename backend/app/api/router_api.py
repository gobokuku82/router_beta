from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import asyncio
import logging
import sys
from pathlib import Path
from datetime import datetime
import sqlite3
import json
import uuid

# 경로 설정
backend_dir = Path(__file__).parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.services.router_agent.router_agent import RouterAgent, AVAILABLE_AGENT_IDS, AGENT_DESCS
from app.services.router_agent.task_router import task_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Context Manager import with error handling
context_manager = None
sync_context_manager = None
try:
    from app.services.common.context_manager import context_manager as cm, sync_context_manager as scm
    context_manager = cm
    sync_context_manager = scm
    logger.info("Context Manager imported successfully")
except Exception as e:
    logger.error(f"Failed to import context_manager: {e}")
    context_manager = None

router = APIRouter()

# Chat History Integration import
chat_integration = None
try:
    from app.services.common.chat_history_integration import chat_integration as chi
    chat_integration = chi
    logger.info("Chat History Integration imported successfully")
except Exception as e:
    logger.error(f"Failed to import chat_history_integration: {e}")
    chat_integration = None

# SQLite DB 경로
DB_PATH = backend_dir / "chat_history.db"

def init_db():
    """데이터베이스 초기화"""
    try:
        with sqlite3.connect(str(DB_PATH)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    message_id TEXT UNIQUE NOT NULL,
                    timestamp TEXT NOT NULL,
                    role TEXT NOT NULL,
                    message_text TEXT NOT NULL,
                    metadata TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_session ON chat_history(session_id)")
            conn.commit()
        logger.info(f"Database initialized at: {DB_PATH}")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")

# DB 초기화
try:
    init_db()
except Exception as e:
    logger.error(f"DB initialization error: {e}")

def save_message(session_id: str, role: str, message_text: str, metadata: Dict = None):
    """메시지를 DB에 저장"""
    message_id = str(uuid.uuid4())
    timestamp = datetime.now().isoformat()
    
    try:
        with sqlite3.connect(str(DB_PATH)) as conn:
            conn.execute("""
                INSERT INTO chat_history 
                (session_id, message_id, timestamp, role, message_text, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                message_id,
                timestamp,
                role,
                message_text,
                json.dumps(metadata or {}, ensure_ascii=False)
            ))
            conn.commit()
        logger.info(f"[SAVED] {role} message for session {session_id}")
        return message_id
    except Exception as e:
        logger.error(f"Failed to save message: {e}")
        return None

# 요청 모델
class QueryRequest(BaseModel):
    session_id: str
    query: str

class SelectionRequest(BaseModel):
    session_id: str
    agent: Optional[str] = None
    selected_agent: Optional[str] = None
    query: str

# 세션 관리
sessions = {}

# Router Agent 인스턴스 (싱글톤)
try:
    router_agent = RouterAgent()
    logger.info("RouterAgent 초기화 성공")
except Exception as e:
    logger.error(f"RouterAgent 초기화 실패: {e}")
    router_agent = None

# 에이전트 표시 이름
AGENT_DISPLAY_NAMES = {
    "employee_agent": "직원 실적 분석",
    "client_agent": "고객/거래처 분석", 
    "search_agent": "정보 검색",
    "docs_agent": "문서 생성"
}

# 에이전트별 예시 질문
AGENT_EXAMPLE_QUESTIONS = {
    "employee_agent": [
        "김철수 사원의 이번 달 실적을 보여주세요",
        "영업1팀의 평균 매출액은 얼마인가요?",
        "작년 우수 사원 명단을 조회해주세요",
        "영업본부 조직도를 보여주세요"
    ],
    "client_agent": [
        "A병원의 월별 구매 추이를 분석해주세요",
        "서울 지역 약국 거래처 목록을 보여주세요",
        "이번 달 신규 거래처는 몇 개인가요?",
        "VIP 등급 병원들의 주요 구매 품목은?"
    ],
    "search_agent": [
        "항생제 제품 카탈로그를 검색해주세요",
        "영업 매뉴얼에서 계약 절차를 찾아주세요",
        "사내 휴가 규정을 검색해주세요",
        "신제품 교육 자료를 찾아주세요"
    ],
    "docs_agent": [
        "이번 달 영업 실적 보고서를 작성해주세요",
        "거래처 방문 보고서 템플릿을 만들어주세요",
        "분기별 매출 분석 문서를 생성해주세요",
        "신규 거래처 제안서를 작성해주세요"
    ]
}

async def run_agent(agent_id: str, query: str, session_id: str) -> Dict[str, Any]:
    """각 에이전트의 run.py 실행"""
    try:
        if agent_id == "employee_agent":
            from app.services.employee_agent import run
            result = await run(query, session_id)
            return result
            
        elif agent_id == "client_agent":
            from app.services.client_agent import run
            result = await run(query, session_id)
            return result
            
        elif agent_id == "search_agent":
            from app.services.search_agent.run import run
            result = await run(query, session_id)
            return result
            
        elif agent_id == "docs_agent":
            from app.services.docs_agent import run
            result = await run(query, session_id)
            return result
            
        else:
            raise ValueError(f"알 수 없는 에이전트: {agent_id}")
            
    except Exception as e:
        logger.error(f"에이전트 실행 오류 ({agent_id}): {e}")
        return {
            "success": False,
            "error": str(e),
            "agent": agent_id
        }

@router.post("/chat")
async def chat(req: QueryRequest):
    """메인 채팅 엔드포인트 - RouterAgent를 통한 자동 라우팅"""
    try:
        # 세션 초기화
        if req.session_id not in sessions:
            sessions[req.session_id] = {
                "messages": [],
                "routing_attempts": 0,
                "fixed_agent": None,  # 고정된 에이전트
                "agent_fixed_at": None  # 고정 시간
            }
        
        session = sessions[req.session_id]
        
        # 사용자 메시지를 PostgreSQL에 저장
        try:
            if chat_integration:
                await chat_integration.process_user_message(
                    session_id=req.session_id,
                    query=req.query,
                    employee_id=1  # TODO: 실제 사용자 인증에서 가져와야 함
                )
            else:
                logger.error("사용자 메시지를 PostgreSQL에 저장 실패")
        except Exception as e:
            logger.error(f"Failed to save user message: {e}")
        
        # 이전 대화 컨텍스트 로드
        conversation_context = None
        if chat_integration:
            try:
                conversation_context = await chat_integration.get_conversation_context(
                    session_id=req.session_id,
                    max_messages=10
                )
                logger.info(f"Loaded {len(conversation_context.get('messages', []))} previous messages")
            except Exception as e:
                logger.error(f"Failed to load conversation context: {e}")
        
        # 쿼리 처리 - enhanced_query를 안전하게 처리
        query_to_process = req.query
        
        if sync_context_manager:
            try:
                # 동기 래퍼 사용
                query_to_process = sync_context_manager.process_query(req.session_id, req.query)
                logger.info(f"원본 쿼리: '{req.query}' -> 보완된 쿼리: '{query_to_process}'")
            except Exception as e:
                logger.error(f"Context processing error: {e}")
                query_to_process = req.query
        else:
            logger.warning("Context manager not available, using original query")
        
        session["messages"].append({"role": "user", "content": req.query})
        
        # 먼저 task_router로 처리 시도 (멀티 태스크 지원)
        try:
            task_result = await task_router.process_query(
                query=query_to_process,
                session_id=req.session_id,
                messages=session["messages"]
            )
            
            # 멀티 태스크로 처리된 경우
            if task_result.get("type") in ["multi", "single"]:
                # 단일 태스크인 경우 바로 반환
                if task_result.get("type") == "single":
                    response_data = task_result.get("response", "처리할 수 없습니다.")
                    
                    # 메시지 저장
                    save_message(req.session_id, "assistant", str(response_data), {
                        "type": "single",
                        "tasks": task_result.get("tasks", [])
                    })
                    
                    # 세션 메시지 업데이트
                    session["messages"].append({"role": "assistant", "content": str(response_data)})
                    
                    return {
                        "success": True,
                        "response": response_data,
                        "agent": task_result.get("tasks", [{}])[0].get("agent", "unknown"),
                        "type": "single"
                    }
                
                # 멀티 태스크인 경우 - 첫 번째 작업만 실행하고 나머지는 pending으로 반환
                if task_result.get("type") == "multi":
                    # detailed_results가 있으면 첫 번째 결과만 반환
                    if task_result.get("detailed_results"):
                        first_task_id = min(task_result["detailed_results"].keys())
                        first_result = task_result["detailed_results"][first_task_id]
                        first_task = next((t for t in task_result["tasks"] if t["id"] == first_task_id), None)
                        
                        # 나머지 작업들
                        remaining_tasks = [t for t in task_result["tasks"] if t["id"] != first_task_id]
                        
                        # 첫 번째 작업 결과만 저장
                        save_message(req.session_id, "assistant", str(first_result), {
                            "type": "single",
                            "task": first_task
                        })
                        
                        session["messages"].append({"role": "assistant", "content": str(first_result)})
                        
                        # docs_agent가 마지막 작업인지 확인
                        is_last_docs = (len(remaining_tasks) == 1 and 
                                      remaining_tasks[0].get("agent") in ["docs_agent", "create_document_agent"])
                        
                        return {
                            "success": True,
                            "response": first_result,
                            "agent": first_task.get("agent", "unknown") if first_task else "unknown",
                            "type": "single",
                            "remaining_tasks": remaining_tasks,
                            "total_tasks": len(task_result["tasks"]),
                            "current_task_index": 1,
                            "auto_execute": not is_last_docs  # docs_agent가 마지막이 아니면 자동 실행
                        }
                    else:
                        # detailed_results가 없으면 전체 응답 반환 (기존 방식)
                        return task_result
                
        except Exception as e:
            logger.warning(f"Task router failed, falling back to single agent: {e}")
            # task_router 실패 시에도 계속 처리
        
        # 단일 에이전트 처리 (기존 로직)
        classified_agent = None
        max_attempts = 3
        
        if router_agent:
            for attempt in range(max_attempts):
                session["routing_attempts"] = attempt + 1
                # 보완된 쿼리로 분류
                classified_agent = await router_agent.classify(query_to_process, session["messages"])
                
                if classified_agent and classified_agent in AVAILABLE_AGENT_IDS:
                    logger.info(f"분류 성공 (시도 {attempt + 1}): {classified_agent}")
                    break
                    
                logger.warning(f"분류 실패 (시도 {attempt + 1})")
                await asyncio.sleep(0.5)  # 재시도 전 대기
        
        # 분류 실패 시 수동 선택 필요
        if not classified_agent:
            fallback_message = f"""죄송합니다. '{req.query}' 질문이 저희 시스템의 기능과 관련이 없거나 분류가 어렵습니다.

저희 시스템은 다음 기능을 제공합니다:
- 직원 실적/평가 조회
- 고객/거래처(병원,약국) 정보 관리  
- 영업 데이터 검색
- 보고서/문서 자동 생성

해당하는 기능이 있다면 아래에서 선택해주세요:"""
            
            return {
                "success": True,
                "needs_user_selection": True,
                "message": fallback_message,
                "available_agents": AVAILABLE_AGENT_IDS,
                "agent_descriptions": AGENT_DESCS,
                "agent_display_names": AGENT_DISPLAY_NAMES,
                "routing_attempts": session["routing_attempts"]
            }
        
        # 에이전트 실행
        result = await run_agent(classified_agent, query_to_process, req.session_id)
        result["routing_attempts"] = session["routing_attempts"]
        result["classification_result"] = f"자동 분류: {classified_agent}"
        
        # 응답 저장
        session["messages"].append({
            "role": "assistant",
            "content": result.get("response", ""),
            "agent": classified_agent
        })
        
        # AI 응답을 PostgreSQL에 저장
        try:
            if chat_integration:
                await chat_integration.process_assistant_response(
                    session_id=req.session_id,
                    response=result.get("response", ""),
                    agent_name=classified_agent,
                    employee_id=1  # TODO: 실제 사용자 인증에서 가져와야 함
                )
            else:
                logger.error("AI 응답을 PostgreSQL에 저장 실패")
        except Exception as e:
            logger.error(f"Failed to save assistant response: {e}")
        
        # 컨텍스트 업데이트
        if sync_context_manager:
            try:
                sync_context_manager.update_context(req.session_id, req.query, result)
            except Exception as e:
                logger.error(f"Context update error: {e}")
        
        return result
        
    except Exception as e:
        logger.error(f"Chat error: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "response": "처리 중 오류가 발생했습니다."
        }

@router.post("/select-agent")
async def select_agent(req: SelectionRequest):
    """사용자가 직접 에이전트 선택"""
    try:
        agent_id = req.selected_agent or req.agent
        
        if not agent_id or agent_id not in AVAILABLE_AGENT_IDS:
            return {
                "success": False,
                "error": "유효하지 않은 에이전트입니다."
            }
        
        # 세션 초기화
        if req.session_id not in sessions:
            sessions[req.session_id] = {
                "messages": [],
                "routing_attempts": 0
            }
        
        # 사용자가 새 질문을 입력하지 않았다면 예시 질문 제공
        if not req.query or req.query == "" or req.query == req.selected_agent:
            agent_name = AGENT_DISPLAY_NAMES.get(agent_id, agent_id)
            example_questions = AGENT_EXAMPLE_QUESTIONS.get(agent_id, [])
            
            guide_message = f"""{agent_name}을(를) 선택하셨습니다.

이 에이전트는 다음과 같은 질문에 답변할 수 있습니다:
"""
            for i, example in enumerate(example_questions, 1):
                guide_message += f"\n{i}. {example}"
            
            guide_message += "\n\n위 예시를 참고하여 질문을 입력해주세요."
            
            return {
                "success": True,
                "agent_selected": True,
                "needs_new_question": True,
                "selected_agent": agent_id,
                "message": guide_message,
                "example_questions": example_questions
            }
        
        # 쿼리 처리
        query_to_process = req.query
        
        if sync_context_manager:
            try:
                # 동기 래퍼 사용
                query_to_process = sync_context_manager.process_query(req.session_id, req.query)
                logger.info(f"원본 쿼리: '{req.query}' -> 보완된 쿼리: '{query_to_process}'")
            except Exception as e:
                logger.error(f"Context processing error: {e}")
                query_to_process = req.query
        else:
            logger.warning("Context manager not available, using original query")
        
        # 사용자 메시지를 PostgreSQL에 저장
        try:
            if chat_integration:
                await chat_integration.process_user_message(
                    session_id=req.session_id,
                    query=req.query,
                    employee_id=1  # TODO: 실제 사용자 인증에서 가져와야 함
                )
            else:
                logger.error("사용자 메시지를 PostgreSQL에 저장 실패")
        except Exception as e:
            logger.error(f"Failed to save user message: {e}")
        
        # 질문이 있으면 에이전트 실행
        result = await run_agent(agent_id, query_to_process, req.session_id)
        result["agent_selected"] = True
        result["classification_result"] = f"사용자 선택: {agent_id}"
        
        # AI 응답을 PostgreSQL에 저장
        try:
            if chat_integration:
                await chat_integration.process_assistant_response(
                    session_id=req.session_id,
                    response=result.get("response", ""),
                    agent_name=agent_id,
                    employee_id=1  # TODO: 실제 사용자 인증에서 가져와야 함
                )
            else:
                logger.error("AI 응답을 PostgreSQL에 저장 실패")
        except Exception as e:
            logger.error(f"Failed to save assistant response: {e}")
        
        # 세션에 메시지 저장 (메모리)
        sessions[req.session_id]["messages"].append({
            "role": "user",
            "content": req.query
        })
        sessions[req.session_id]["messages"].append({
            "role": "assistant",
            "content": result.get("response", ""),
            "agent": agent_id
        })
        
        # 컨텍스트 업데이트
        if sync_context_manager:
            try:
                sync_context_manager.update_context(req.session_id, req.query, result)
            except Exception as e:
                logger.error(f"Context update error: {e}")
        
        return result
        
    except Exception as e:
        logger.error(f"Select agent error: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }

@router.post("/initial-agent-select")
async def initial_agent_select(req: SelectionRequest):
    """초기 화면에서 에이전트 직접 선택"""
    try:
        agent_id = req.selected_agent or req.agent
        
        if not agent_id or agent_id not in AVAILABLE_AGENT_IDS:
            return {
                "success": False,
                "error": "유효하지 않은 에이전트입니다."
            }
        
        # 세션 초기화
        if req.session_id not in sessions:
            sessions[req.session_id] = {
                "messages": [],
                "routing_attempts": 0
            }
        
        # 선택된 에이전트 정보와 예시 질문 제공
        agent_name = AGENT_DISPLAY_NAMES.get(agent_id, agent_id)
        example_questions = AGENT_EXAMPLE_QUESTIONS.get(agent_id, [])
        
        guide_message = f"""{agent_name}을(를) 선택하셨습니다.

이 에이전트는 다음과 같은 질문에 답변할 수 있습니다:
"""
        for i, example in enumerate(example_questions, 1):
            guide_message += f"\n{i}. {example}"
        
        guide_message += "\n\n위 예시를 참고하여 질문을 입력해주세요."
        
        return {
            "success": True,
            "agent_selected": True,
            "needs_new_question": True,
            "selected_agent": agent_id,
            "message": guide_message,
            "example_questions": example_questions
        }
        
    except Exception as e:
        logger.error(f"Initial agent select error: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }

@router.get("/test")
async def test():
    """테스트 엔드포인트"""
    return {"message": "API is working!", "status": "ok"}

@router.get("/chat-history")
async def get_chat_history():
    """채팅 기록"""
    history = []
    for session_id, data in sessions.items():
        history.append({
            "session_id": session_id,
            "message_count": len(data.get("messages", [])),
            "selected_agent": data.get("selected_agent"),
            "created_at": data.get("created_at", "")
        })
    
    return {
        "success": True,
        "chatHistory": history,
        "count": len(history)
    }

@router.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    """세션별 메시지"""
    if session_id in sessions:
        messages = sessions[session_id].get("messages", [])
        return {
            "success": True,
            "messages": messages,
            "count": len(messages)
        }
    
    return {
        "success": True,
        "messages": [],
        "count": 0
    }

@router.get("/current-agent/{session_id}")
async def get_current_agent(session_id: str):
    """현재 세션의 마지막 사용 에이전트 확인"""
    if session_id in sessions:
        messages = sessions[session_id].get("messages", [])
        # 마지막 assistant 메시지에서 에이전트 정보 찾기
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and msg.get("agent"):
                agent = msg["agent"]
                return {
                    "success": True,
                    "has_selected_agent": False,  # 고정되지 않음
                    "last_agent": {
                        "agent_name": AGENT_DISPLAY_NAMES.get(agent, agent),
                        "agent_key": agent
                    }
                }
    
    return {
        "success": True,
        "has_selected_agent": False,
        "agent": None
    }

@router.post("/reset-agent")
async def reset_agent(req: Dict[str, Any]):
    """대화 이력 리셋"""
    session_id = req.get("session_id")
    if session_id and session_id in sessions:
        sessions[session_id]["messages"] = []
        sessions[session_id]["routing_attempts"] = 0
    
    return {
        "success": True,
        "message": "대화 이력이 초기화되었습니다."
    }

@router.get("/chat-history/{session_id}")
async def get_chat_history(
    session_id: str,
    limit: int = 50,
    offset: int = 0
):
    """세션의 대화 기록 조회"""
    try:
        if chat_integration:
            # PostgreSQL에서 조회
            messages = await chat_integration.history_manager.get_conversation_history(
                session_id=session_id,
                limit=limit,
                offset=offset
            )
            
            return {
                "success": True,
                "session_id": session_id,
                "messages": messages,
                "count": len(messages),
                "db_type": "postgresql"
            }
        else:
            logger.error("PostgreSql에서 세션의 대화 기록 조회 실패")
            return {
                "success": False,
                "error": "Chat integration not available"
            }
    except Exception as e:
        logger.error(f"Failed to get chat history: {e}")
        return {
            "success": False,
            "error": str(e)
        }

@router.get("/session-info/{session_id}")
async def get_session_info(session_id: str):
    """세션 정보 조회"""
    try:
        if chat_integration:
            # PostgreSQL에서 조회
            session_info = await chat_integration.history_manager.get_session_info(session_id)
            
            if session_info:
                return {
                    "success": True,
                    "session": {
                        "session_id": session_id,
                        "first_message": session_info["created_at"],
                        "last_message": session_info["last_activity"],
                        "message_count": session_info["message_count"]
                    },
                    "db_type": "postgresql"
                }
            else:
                return {"success": False, "error": "Session not found"}
        else:
            logger.error("PostgreSql에서 세션 기록 조회 실패")
            return {
                "success": False,
                "error": "Chat integration not available"
            }
    except Exception as e:
        logger.error(f"Failed to get session info: {e}")
        return {
            "success": False,
            "error": str(e)
        }

@router.get("/all-sessions")
async def get_all_sessions():
    """모든 세션 목록 조회"""
    try:
        if chat_integration:
            # PostgreSQL에서 세션 목록 조회
            sessions = await chat_integration.history_manager.get_all_sessions(limit=50)
            
            return {
                "success": True,
                "sessions": sessions,
                "count": len(sessions),
                "db_type": "postgresql"
            }
        else:
            logger.error("PostgreSql에서 세션 목록 조회 실패")
            return {
                "success": False,
                "error": "Chat integration not available"
            }
    except Exception as e:
        logger.error(f"Failed to get all sessions: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@router.post("/route/router")
async def route_router(req: Dict[str, Any]):
    """
    프론트엔드 호환성을 위한 라우터 엔드포인트
    /chat/multi로 리다이렉트
    """
    try:
        # QueryRequest 형태로 변환
        query_req = QueryRequest(
            session_id=req.get("session_id", f"session_{int(datetime.now().timestamp())}"),
            query=req.get("query", "")
        )
        
        # multi_task_chat 호출
        return await multi_task_chat(query_req)
        
    except Exception as e:
        logger.error(f"Route router error: {str(e)}")
        return {
            "success": False,
            "response": f"요청 처리 중 오류가 발생했습니다: {str(e)}",
            "error": str(e)
        }


@router.post("/chat/multi")
async def multi_task_chat(req: QueryRequest):
    """
    멀티 태스크 처리를 지원하는 새로운 채팅 엔드포인트
    단일 태스크와 멀티 태스크를 자동으로 구분하여 처리
    """
    try:
        # 세션 확인
        if req.session_id not in sessions:
            sessions[req.session_id] = {
                "messages": [],
                "routing_attempts": 0
            }
        
        session = sessions[req.session_id]
        
        # 사용자 메시지 저장
        save_message(req.session_id, "user", req.query)
        
        # 이전 대화 컨텍스트 로드
        conversation_context = None
        if chat_integration:
            try:
                conversation_context = await chat_integration.get_conversation_context(
                    session_id=req.session_id,
                    max_messages=10
                )
                logger.info(f"Loaded {len(conversation_context.get('messages', []))} previous messages")
            except Exception as e:
                logger.error(f"Failed to load conversation context: {e}")
        
        # 쿼리 처리 - context manager 적용
        query_to_process = req.query
        
        if sync_context_manager:
            try:
                query_to_process = sync_context_manager.process_query(req.session_id, req.query)
                logger.info(f"원본 쿼리: '{req.query}' -> 보완된 쿼리: '{query_to_process}'")
            except Exception as e:
                logger.error(f"Context processing error: {e}")
                query_to_process = req.query
        
        # 태스크 라우터로 처리
        result = await task_router.process_query(
            query=query_to_process,
            session_id=req.session_id,
            messages=session["messages"]
        )
        
        # 결과 저장
        response_data = result.get("response", "처리할 수 없습니다.")
        
        # response가 딕셔너리인 경우 (멀티 태스크) summary를 텍스트로 사용
        if isinstance(response_data, dict):
            response_text = response_data.get("summary", "처리할 수 없습니다.")
        else:
            response_text = response_data
            
        save_message(req.session_id, "assistant", response_text, {
            "type": result.get("type", "unknown"),
            "tasks": result.get("tasks", []),
            "response_data": response_data if isinstance(response_data, dict) else None
        })
        
        # 세션 메시지 업데이트
        session["messages"].append({"role": "user", "content": req.query})
        session["messages"].append({"role": "assistant", "content": response_text})
        
        # 응답 반환
        return {
            "success": True,
            "response": response_data,  # 구조화된 응답 그대로 반환
            "type": result.get("type"),
            "tasks": result.get("tasks", []),
            "detailed_results": result.get("detailed_results") if result.get("type") == "multi" else None,
            "execution_plan": result.get("execution_plan") if result.get("type") == "multi" else None
        }
        
    except Exception as e:
        logger.error(f"Multi-task chat error: {str(e)}")
        error_message = "죄송합니다. 요청을 처리하는 중 오류가 발생했습니다."
        
        # 오류 메시지도 저장
        save_message(req.session_id, "assistant", error_message, {"error": str(e)})
        
        return {
            "success": False,
            "response": error_message,
            "error": str(e)
        }