"""
채팅 히스토리 관리 모듈 (고도화 버전)
세션별 대화 기록을 저장하고 관리합니다.
aiosqlite가 없어도 작동하는 fallback 지원
"""
import uuid
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any
from pathlib import Path
import sqlite3
import logging
import asyncio
from functools import partial

# aiosqlite 의존성 처리
try:
    import aiosqlite
    HAS_AIOSQLITE = True
except ImportError:
    HAS_AIOSQLITE = False

logger = logging.getLogger(__name__)

class ChatHistoryManager:
    """채팅 히스토리 관리 클래스 (고도화 버전)"""
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Args:
            db_path: 데이터베이스 경로. None이면 기본 경로 사용
        """
        if db_path is None:
            # 기본 경로: backend/chat_history/chat_history.db
            base_dir = Path(__file__).parent.parent.parent
            self.db_path = base_dir / "chat_history" / "chat_history.db"
        else:
            self.db_path = Path(db_path)
            
        # 디렉토리 생성
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 메모리 캐시 (DB 실패 시 임시 저장)
        self._memory_cache = []
        self._cache_lock = asyncio.Lock()
        
        # 동기 방식으로 초기화 (앱 시작 시)
        self._init_db_sync()
        
        # aiosqlite 사용 불가 경고
        if not HAS_AIOSQLITE:
            logger.warning("aiosqlite not installed. Using synchronous sqlite3 with thread executor.")
        
    def _init_db_sync(self):
        """동기 방식으로 데이터베이스 초기화"""
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                # 테이블 생성 (인덱스는 별도로 생성)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS chat_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        message_id TEXT UNIQUE NOT NULL,
                        timestamp TEXT NOT NULL,
                        role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                        message_text TEXT NOT NULL,
                        metadata TEXT
                    )
                """)
                
                # 인덱스 별도 생성
                conn.execute("CREATE INDEX IF NOT EXISTS idx_session_id ON chat_history(session_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON chat_history(timestamp)")
                
                # 세션 정보 테이블
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS chat_sessions (
                        session_id TEXT PRIMARY KEY,
                        created_at TEXT NOT NULL,
                        last_activity TEXT NOT NULL,
                        metadata TEXT
                    )
                """)
                
                # 세션 테이블 인덱스
                conn.execute("CREATE INDEX IF NOT EXISTS idx_last_activity ON chat_sessions(last_activity)")
                
                conn.commit()
                logger.info(f"ChatHistory DB initialized at: {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise
    
    async def _execute_db_operation(self, operation_func, *args, **kwargs):
        """데이터베이스 작업 실행 (aiosqlite 또는 동기 방식)"""
        if HAS_AIOSQLITE:
            return await operation_func(*args, **kwargs)
        else:
            # 동기 방식을 비동기로 래핑
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                partial(self._sync_db_operation, operation_func, *args, **kwargs)
            )
    
    def _sync_db_operation(self, operation_func, *args, **kwargs):
        """동기 방식 DB 작업"""
        # operation_func의 이름에 따라 적절한 동기 메서드 호출
        func_name = operation_func.__name__
        sync_method = getattr(self, f"_{func_name}_sync", None)
        if sync_method:
            return sync_method(*args, **kwargs)
        else:
            raise NotImplementedError(f"Sync version of {func_name} not implemented")
    
    async def save_message(
        self, 
        session_id: str, 
        role: str, 
        message_text: str,
        metadata: Optional[Dict] = None
    ) -> str:
        """
        메시지 저장 (재시도 메커니즘 포함)
        """
        message_id = str(uuid.uuid4())
        timestamp = datetime.utcnow().isoformat()
        
        # 최대 3회 재시도
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if HAS_AIOSQLITE:
                    async with aiosqlite.connect(str(self.db_path)) as db:
                        # 세션이 없으면 생성
                        await self._ensure_session_exists(db, session_id)
                        
                        # 메시지 저장
                        await db.execute("""
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
                        
                        # 세션 last_activity 업데이트
                        await db.execute("""
                            UPDATE chat_sessions 
                            SET last_activity = ? 
                            WHERE session_id = ?
                        """, (timestamp, session_id))
                        
                        await db.commit()
                else:
                    # 동기 방식
                    await self._save_message_sync(
                        session_id, message_id, timestamp, role, message_text, metadata
                    )
                
                logger.info(f"Message saved: session={session_id}, role={role}, id={message_id}")
                return message_id
                
            except Exception as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.1 * (attempt + 1))
                else:
                    # 마지막 시도도 실패하면 메모리 캐시에 저장
                    async with self._cache_lock:
                        self._memory_cache.append({
                            "session_id": session_id,
                            "message_id": message_id,
                            "timestamp": timestamp,
                            "role": role,
                            "message_text": message_text,
                            "metadata": metadata
                        })
                    logger.error(f"Failed to save message after {max_retries} attempts. Cached in memory: {e}")
                    return message_id
    
    async def _save_message_sync(self, session_id, message_id, timestamp, role, message_text, metadata):
        """동기 방식으로 메시지 저장 (비동기 래퍼)"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._save_message_sync_impl, 
                                  session_id, message_id, timestamp, role, message_text, metadata)
    
    def _save_message_sync_impl(self, session_id, message_id, timestamp, role, message_text, metadata):
        """동기 방식으로 메시지 저장 (실제 구현)"""
        with sqlite3.connect(str(self.db_path)) as conn:
            # 세션이 없으면 생성
            cursor = conn.execute(
                "SELECT session_id FROM chat_sessions WHERE session_id = ?",
                (session_id,)
            )
            if not cursor.fetchone():
                conn.execute("""
                    INSERT INTO chat_sessions (session_id, created_at, last_activity, metadata)
                    VALUES (?, ?, ?, ?)
                """, (session_id, timestamp, timestamp, "{}"))
            
            # 메시지 저장
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
            
            # 세션 업데이트
            conn.execute("""
                UPDATE chat_sessions 
                SET last_activity = ? 
                WHERE session_id = ?
            """, (timestamp, session_id))
            
            conn.commit()
    
    async def _ensure_session_exists(self, db, session_id: str):
        """세션이 존재하는지 확인하고 없으면 생성"""
        cursor = await db.execute(
            "SELECT session_id FROM chat_sessions WHERE session_id = ?",
            (session_id,)
        )
        result = await cursor.fetchone()
        
        if not result:
            timestamp = datetime.utcnow().isoformat()
            await db.execute("""
                INSERT INTO chat_sessions (session_id, created_at, last_activity, metadata)
                VALUES (?, ?, ?, ?)
            """, (session_id, timestamp, timestamp, "{}"))
    
    async def get_conversation_history(
        self, 
        session_id: str,
        limit: Optional[int] = None,
        offset: int = 0
    ) -> List[Dict]:
        """대화 기록 조회"""
        try:
            if HAS_AIOSQLITE:
                async with aiosqlite.connect(str(self.db_path)) as db:
                    query = """
                        SELECT message_id, timestamp, role, message_text, metadata
                        FROM chat_history
                        WHERE session_id = ?
                        ORDER BY timestamp ASC
                    """
                    
                    if limit:
                        query += f" LIMIT {limit} OFFSET {offset}"
                        
                    cursor = await db.execute(query, (session_id,))
                    rows = await cursor.fetchall()
            else:
                # 동기 방식
                loop = asyncio.get_event_loop()
                rows = await loop.run_in_executor(
                    None,
                    self._get_conversation_history_sync,
                    session_id, limit, offset
                )
            
            messages = []
            for row in rows:
                messages.append({
                    "message_id": row[0],
                    "timestamp": row[1],
                    "role": row[2],
                    "content": row[3],
                    "metadata": json.loads(row[4])
                })
            
            # 메모리 캐시에서도 확인
            async with self._cache_lock:
                for cached_msg in self._memory_cache:
                    if cached_msg["session_id"] == session_id:
                        messages.append({
                            "message_id": cached_msg["message_id"],
                            "timestamp": cached_msg["timestamp"],
                            "role": cached_msg["role"],
                            "content": cached_msg["message_text"],
                            "metadata": cached_msg.get("metadata", {})
                        })
                
            return messages
            
        except Exception as e:
            logger.error(f"Failed to get conversation history: {e}")
            return []
    
    def _get_conversation_history_sync(self, session_id, limit, offset):
        """동기 방식으로 대화 기록 조회"""
        with sqlite3.connect(str(self.db_path)) as conn:
            query = """
                SELECT message_id, timestamp, role, message_text, metadata
                FROM chat_history
                WHERE session_id = ?
                ORDER BY timestamp ASC
            """
            
            if limit:
                query += f" LIMIT {limit} OFFSET {offset}"
                
            cursor = conn.execute(query, (session_id,))
            return cursor.fetchall()
    
    async def get_recent_context(
        self, 
        session_id: str, 
        message_count: int = 10
    ) -> List[Dict]:
        """최근 대화 컨텍스트 가져오기"""
        try:
            if HAS_AIOSQLITE:
                async with aiosqlite.connect(str(self.db_path)) as db:
                    cursor = await db.execute("""
                        SELECT message_id, timestamp, role, message_text, metadata
                        FROM chat_history
                        WHERE session_id = ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                    """, (session_id, message_count))
                    
                    rows = await cursor.fetchall()
            else:
                # 동기 방식
                loop = asyncio.get_event_loop()
                rows = await loop.run_in_executor(
                    None,
                    self._get_recent_context_sync,
                    session_id, message_count
                )
            
            # 시간 순서대로 정렬 (오래된 것부터)
            messages = []
            for row in reversed(rows):
                messages.append({
                    "message_id": row[0],
                    "timestamp": row[1],
                    "role": row[2],
                    "content": row[3],
                    "metadata": json.loads(row[4])
                })
                
            return messages
            
        except Exception as e:
            logger.error(f"Failed to get recent context: {e}")
            return []
    
    def _get_recent_context_sync(self, session_id, message_count):
        """동기 방식으로 최근 컨텍스트 조회"""
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.execute("""
                SELECT message_id, timestamp, role, message_text, metadata
                FROM chat_history
                WHERE session_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (session_id, message_count))
            return cursor.fetchall()
    
    async def get_session_info(self, session_id: str) -> Optional[Dict]:
        """세션 정보 조회"""
        try:
            if HAS_AIOSQLITE:
                async with aiosqlite.connect(str(self.db_path)) as db:
                    cursor = await db.execute("""
                        SELECT created_at, last_activity, metadata
                        FROM chat_sessions
                        WHERE session_id = ?
                    """, (session_id,))
                    
                    row = await cursor.fetchone()
            else:
                # 동기 방식
                loop = asyncio.get_event_loop()
                row = await loop.run_in_executor(
                    None,
                    self._get_session_info_sync,
                    session_id
                )
            
            if row:
                return {
                    "session_id": session_id,
                    "created_at": row[0],
                    "last_activity": row[1],
                    "metadata": json.loads(row[2])
                }
            return None
            
        except Exception as e:
            logger.error(f"Failed to get session info: {e}")
            return None
    
    def _get_session_info_sync(self, session_id):
        """동기 방식으로 세션 정보 조회"""
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.execute("""
                SELECT created_at, last_activity, metadata
                FROM chat_sessions
                WHERE session_id = ?
            """, (session_id,))
            return cursor.fetchone()
    
    async def delete_old_sessions(self, days: int = 30):
        """오래된 세션 삭제"""
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        cutoff_str = cutoff_date.isoformat()
        
        try:
            if HAS_AIOSQLITE:
                async with aiosqlite.connect(str(self.db_path)) as db:
                    # 메시지도 함께 삭제
                    await db.execute("""
                        DELETE FROM chat_history
                        WHERE session_id IN (
                            SELECT session_id FROM chat_sessions
                            WHERE last_activity < ?
                        )
                    """, (cutoff_str,))
                    
                    # 세션 삭제
                    await db.execute("""
                        DELETE FROM chat_sessions
                        WHERE last_activity < ?
                    """, (cutoff_str,))
                    
                    await db.commit()
            else:
                # 동기 방식
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    self._delete_old_sessions_sync,
                    cutoff_str
                )
                
            logger.info(f"Deleted sessions older than {days} days")
            
        except Exception as e:
            logger.error(f"Failed to delete old sessions: {e}")
    
    def _delete_old_sessions_sync(self, cutoff_str):
        """동기 방식으로 오래된 세션 삭제"""
        with sqlite3.connect(str(self.db_path)) as conn:
            # 메시지 삭제
            conn.execute("""
                DELETE FROM chat_history
                WHERE session_id IN (
                    SELECT session_id FROM chat_sessions
                    WHERE last_activity < ?
                )
            """, (cutoff_str,))
            
            # 세션 삭제
            conn.execute("""
                DELETE FROM chat_sessions
                WHERE last_activity < ?
            """, (cutoff_str,))
            
            conn.commit()
    
    async def flush_memory_cache(self):
        """메모리 캐시를 DB로 플러시"""
        if not self._memory_cache:
            return
            
        async with self._cache_lock:
            cache_copy = self._memory_cache.copy()
            self._memory_cache.clear()
        
        for msg in cache_copy:
            try:
                await self.save_message(
                    msg["session_id"],
                    msg["role"],
                    msg["message_text"],
                    msg.get("metadata")
                )
            except Exception as e:
                logger.error(f"Failed to flush cached message: {e}")
                # 실패한 메시지는 다시 캐시에 추가
                async with self._cache_lock:
                    self._memory_cache.append(msg)

# 싱글톤 인스턴스
chat_history_manager = ChatHistoryManager()