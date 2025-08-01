"""
PostgreSQL 기반 채팅 히스토리 관리 모듈
세션별 대화 기록을 PostgreSQL에 저장하고 관리합니다.
"""
import uuid
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import logging
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc
from concurrent.futures import ThreadPoolExecutor
import asyncio

# PostgreSQL 관련 import
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'database'))
from database.services.db import SessionLocal
from database.models import ChatHistory, ChatSession

logger = logging.getLogger(__name__)

class PostgresChatHistoryManager:
    """PostgreSQL 기반 채팅 히스토리 관리 클래스"""
    
    def __init__(self):
        """PostgreSQL 연결 초기화"""
        self.executor = ThreadPoolExecutor(max_workers=4)
        logger.info("PostgresChatHistoryManager initialized")
    
    def _get_db_session(self) -> Session:
        """데이터베이스 세션 생성"""
        return SessionLocal()
    
    async def save_message(
        self, 
        session_id: str, 
        role: str, 
        message_text: str,
        employee_id: int
    ) -> str:
        """
        메시지 저장
        
        Args:
            session_id: 세션 ID
            role: 'user' 또는 'assistant'
            message_text: 메시지 내용
            employee_id: 직원 ID
            
        Returns:
            message_id: 생성된 메시지 ID
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor, 
            self._save_message_sync, 
            session_id, role, message_text, employee_id
        )
    
    def _save_message_sync(
        self, 
        session_id: str, 
        role: str, 
        message_text: str,
        employee_id: int
    ) -> str:
        """동기 방식으로 메시지 저장"""
        db = self._get_db_session()
        try:
            # 세션이 없으면 생성
            self._ensure_session_exists_sync(db, session_id, employee_id)
            
            # TTL 설정 (1년 후 만료)
            expires_at = datetime.utcnow() + timedelta(days=365)
            
            # 메시지 저장
            db_message = ChatHistory(
                session_id=session_id,
                role=role,
                message_text=message_text,
                employee_id=employee_id,
                expires_at=expires_at,
                created_at=datetime.utcnow()
            )
            
            db.add(db_message)
            db.commit()
            db.refresh(db_message)
            
            # 세션 last_activity 업데이트
            session = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
            if session:
                session.last_activity = datetime.utcnow()
                db.commit()
            
            message_id = str(db_message.message_id)
            logger.info(f"Message saved: session={session_id}, role={role}, id={message_id}")
            return message_id
            
        finally:
            db.close()
    
    def _ensure_session_exists_sync(self, db: Session, session_id: str, employee_id: int):
        """세션이 존재하는지 확인하고 없으면 생성"""
        session = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
        
        if not session:
            new_session = ChatSession(
                session_id=session_id,
                employee_id=employee_id,
                created_at=datetime.utcnow(),
                last_activity=datetime.utcnow()
            )
            db.add(new_session)
            db.commit()
    
    async def get_conversation_history(
        self, 
        session_id: str,
        limit: Optional[int] = None,
        offset: int = 0
    ) -> List[Dict]:
        """
        대화 기록 조회
        
        Args:
            session_id: 세션 ID
            limit: 가져올 메시지 수 (None이면 전체)
            offset: 시작 위치
            
        Returns:
            메시지 리스트
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor, 
            self._get_conversation_history_sync, 
            session_id, limit, offset
        )
    
    def _get_conversation_history_sync(
        self, 
        session_id: str,
        limit: Optional[int] = None,
        offset: int = 0
    ) -> List[Dict]:
        """동기 방식으로 대화 기록 조회"""
        db = self._get_db_session()
        try:
            query = db.query(ChatHistory).filter(
                ChatHistory.session_id == session_id
            ).order_by(asc(ChatHistory.created_at))
            
            if limit:
                query = query.limit(limit).offset(offset)
            
            messages = []
            for msg in query.all():
                messages.append({
                    "message_id": str(msg.message_id),
                    "timestamp": msg.created_at.isoformat(),
                    "role": msg.role,
                    "content": msg.message_text
                })
            
            return messages
            
        finally:
            db.close()
    
    async def get_recent_context(
        self, 
        session_id: str, 
        message_count: int = 10
    ) -> List[Dict]:
        """
        최근 대화 컨텍스트 가져오기 (최신 N개)
        
        Args:
            session_id: 세션 ID
            message_count: 가져올 메시지 수
            
        Returns:
            최근 메시지 리스트
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor, 
            self._get_recent_context_sync, 
            session_id, message_count
        )
    
    def _get_recent_context_sync(
        self, 
        session_id: str, 
        message_count: int = 10
    ) -> List[Dict]:
        """동기 방식으로 최근 컨텍스트 조회"""
        db = self._get_db_session()
        try:
            # 최신 메시지부터 조회
            recent_messages = db.query(ChatHistory).filter(
                ChatHistory.session_id == session_id
            ).order_by(desc(ChatHistory.created_at)).limit(message_count).all()
            
            # 시간 순서대로 정렬 (오래된 것부터)
            messages = []
            for msg in reversed(recent_messages):
                messages.append({
                    "message_id": str(msg.message_id),
                    "timestamp": msg.created_at.isoformat(),
                    "role": msg.role,
                    "content": msg.message_text
                })
            
            return messages
            
        finally:
            db.close()
    
    async def get_session_info(self, session_id: str) -> Optional[Dict]:
        """세션 정보 조회"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor, 
            self._get_session_info_sync, 
            session_id
        )
    
    def _get_session_info_sync(self, session_id: str) -> Optional[Dict]:
        """동기 방식으로 세션 정보 조회"""
        db = self._get_db_session()
        try:
            session = db.query(ChatSession).filter(
                ChatSession.session_id == session_id
            ).first()
            
            if session:
                # 메시지 개수 조회
                message_count = db.query(ChatHistory).filter(
                    ChatHistory.session_id == session_id
                ).count()
                
                return {
                    "session_id": session.session_id,
                    "created_at": session.created_at.isoformat(),
                    "last_activity": session.last_activity.isoformat(),
                    "message_count": message_count
                }
            return None
            
        finally:
            db.close()
    
    async def get_message_count(self, session_id: str) -> int:
        """세션의 메시지 개수 조회"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor, 
            self._get_message_count_sync, 
            session_id
        )
    
    def _get_message_count_sync(self, session_id: str) -> int:
        """동기 방식으로 메시지 개수 조회"""
        db = self._get_db_session()
        try:
            count = db.query(ChatHistory).filter(
                ChatHistory.session_id == session_id
            ).count()
            return count
        finally:
            db.close()
    
    async def get_all_sessions(self, limit: int = 50) -> List[Dict]:
        """모든 세션 목록 조회"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor, 
            self._get_all_sessions_sync, 
            limit
        )
    
    def _get_all_sessions_sync(self, limit: int = 50) -> List[Dict]:
        """동기 방식으로 모든 세션 목록 조회"""
        db = self._get_db_session()
        try:
            # 최근 활동 순으로 세션 조회
            sessions = db.query(ChatSession).order_by(
                desc(ChatSession.last_activity)
            ).limit(limit).all()
            
            session_list = []
            for session in sessions:
                # 각 세션의 첫 번째 사용자 메시지 조회
                first_user_message = db.query(ChatHistory).filter(
                    ChatHistory.session_id == session.session_id,
                    ChatHistory.role == "user"
                ).order_by(asc(ChatHistory.created_at)).first()
                
                # 메시지 개수 조회
                message_count = db.query(ChatHistory).filter(
                    ChatHistory.session_id == session.session_id
                ).count()
                
                # 제목 생성 (첫 번째 사용자 메시지 또는 기본값)
                title = "대화"
                if first_user_message:
                    title = first_user_message.message_text[:30]
                    if len(first_user_message.message_text) > 30:
                        title += "..."
                
                session_list.append({
                    "id": session.session_id,
                    "sessionId": session.session_id,
                    "title": title,
                    "firstMessage": session.created_at.isoformat(),
                    "lastMessage": session.last_activity.isoformat(),
                    "messageCount": message_count,
                    "createdAt": session.created_at.isoformat()
                })
            
            return session_list
            
        finally:
            db.close()
    
    async def delete_old_sessions(self, days: int = 30):
        """오래된 세션 삭제"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor, 
            self._delete_old_sessions_sync, 
            days
        )
    
    def _delete_old_sessions_sync(self, days: int = 30):
        """동기 방식으로 오래된 세션 삭제"""
        db = self._get_db_session()
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            # 오래된 세션 삭제 (CASCADE로 메시지도 함께 삭제됨)
            deleted_count = db.query(ChatSession).filter(
                ChatSession.last_activity < cutoff_date
            ).delete()
            
            db.commit()
            logger.info(f"Deleted {deleted_count} sessions older than {days} days")
            
        finally:
            db.close()

# 싱글톤 인스턴스
postgres_chat_history_manager = PostgresChatHistoryManager() 