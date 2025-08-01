"""
Docs Agent Module
문서 생성 에이전트 모듈
"""
from typing import Dict, Any
from .web_interface import web_agent

async def run(query: str, session_id: str) -> Dict[str, Any]:
    """
    문서 생성 에이전트 실행
    router_api.py에서 호출하는 표준 인터페이스
    
    Args:
        query: 사용자 질의
        session_id: 세션 ID
        
    Returns:
        Dict[str, Any]: 실행 결과
    """
    try:
        # 세션 상태 확인
        status = web_agent.get_session_status(session_id)
        
        if not status.get("success"):
            # 새 세션 생성
            result = web_agent.create_session(session_id, query)
        else:
            # 기존 세션에 사용자 입력 처리
            result = web_agent.process_user_input(session_id, query)
            
        # 결과 포맷 변환
        if result.get("success"):
            response_data = {
                "success": True,
                "agent": "docs_agent",
                "session_id": session_id,
                "step": result.get("step"),
                "waiting_for_input": result.get("waiting_for_input", False),
                "input_type": result.get("input_type")
            }
            
            # 단계별 응답 처리
            if result.get("step") == "completed":
                response_data["response"] = result.get("message")
                response_data["document"] = result.get("document")
                response_data["doc_type"] = result.get("doc_type")
                response_data["file_path"] = result.get("file_path")
            else:
                response_data["response"] = result.get("message")
                
                # 옵션이 있는 경우 추가
                if result.get("options"):
                    response_data["options"] = result.get("options")
                    
                # 템플릿 정보가 있는 경우 추가
                if result.get("template"):
                    response_data["template"] = result.get("template")
                    
            return response_data
        else:
            return {
                "success": False,
                "response": result.get("error", "알 수 없는 오류"),
                "error": result.get("error"),
                "agent": "docs_agent",
                "session_id": session_id
            }
            
    except Exception as e:
        return {
            "success": False,
            "response": f"문서 생성 에이전트 실행 중 오류가 발생했습니다: {str(e)}",
            "error": str(e),
            "agent": "docs_agent",
            "session_id": session_id
        }

# 하위 호환성을 위한 별칭
process_query = run