"""
채팅 히스토리 통합 모듈
router_api.py와 각 에이전트에서 사용하기 위한 헬퍼 함수들
"""
from typing import Dict, List, Optional
from .postgres_chat_manager import postgres_chat_history_manager
from .context_manager import context_manager
import logging

logger = logging.getLogger(__name__)

class ChatHistoryIntegration:
    """채팅 히스토리와 컨텍스트 관리를 통합하는 클래스"""
    
    def __init__(self):
        self.history_manager = postgres_chat_history_manager
        self.context_manager = context_manager
    
    async def process_user_message(
        self,
        session_id: str,
        query: str,
        employee_id: int
    ) -> str:
        """
        사용자 메시지 처리 및 저장
        
        Args:
            session_id: 세션 ID
            query: 사용자 질문
            employee_id: 직원 ID
            
        Returns:
            message_id: 저장된 메시지 ID
        """
        # 1. 사용자 메시지 저장
        message_id = await self.history_manager.save_message(
            session_id=session_id,
            role="user",
            message_text=query,
            employee_id=employee_id
        )
        
        # 2. 컨텍스트 매니저 업데이트 (기존 기능 활용)
        # context_manager는 동기식이므로 필요시 수정
        
        logger.info(f"User message processed: {message_id}")
        return message_id
    
    async def process_assistant_response(
        self,
        session_id: str,
        response: str,
        agent_name: str,
        employee_id: int
    ) -> str:
        """
        어시스턴트 응답 처리 및 저장
        
        Args:
            session_id: 세션 ID
            response: AI 응답
            agent_name: 처리한 에이전트 이름
            employee_id: 직원 ID
            
        Returns:
            message_id: 저장된 메시지 ID
        """
        # 응답 저장
        message_id = await self.history_manager.save_message(
            session_id=session_id,
            role="assistant",
            message_text=response,
            employee_id=employee_id
        )
        
        logger.info(f"Assistant response processed: {message_id}")
        return message_id
    
    async def get_conversation_context(
        self,
        session_id: str,
        max_messages: int = 10
    ) -> Dict:
        """
        대화 컨텍스트 조회 (히스토리 + 현재 컨텍스트)
        
        Args:
            session_id: 세션 ID
            max_messages: 최대 메시지 수
            
        Returns:
            컨텍스트 정보
        """
        # 1. 최근 대화 기록
        recent_messages = await self.history_manager.get_recent_context(
            session_id, max_messages
        )
        
        # 2. 현재 컨텍스트 (비동기 호출)
        current_context = await self.context_manager.get_or_create_context(session_id)
        
        return {
            "messages": recent_messages,
            "current_context": {
                "last_person": current_context.last_person,
                "last_client": current_context.last_client,
                "last_topic": current_context.last_topic,
                "last_time_period": current_context.last_time_period
            },
            "session_info": await self.history_manager.get_session_info(session_id)
        }
    
    def format_messages_for_llm(self, messages: List[Dict]) -> List[Dict]:
        """
        LLM에 전달하기 위한 메시지 포맷팅
        
        Args:
            messages: 원본 메시지 리스트
            
        Returns:
            포맷된 메시지 리스트
        """
        formatted = []
        for msg in messages:
            formatted.append({
                "role": msg["role"],
                "content": msg["content"]
            })
        return formatted

# 싱글톤 인스턴스
chat_integration = ChatHistoryIntegration()