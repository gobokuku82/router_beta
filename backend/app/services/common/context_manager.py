"""
컨텍스트 관리자 - 대화 연속성을 위한 문맥 추적 및 관리 (비동기 고도화 버전)
메모리 누수 방지 및 성능 최적화 포함
"""
import re
import asyncio
from typing import Dict, Optional, Any, List
from datetime import datetime, timedelta
import logging
from collections import OrderedDict
import json

logger = logging.getLogger(__name__)


class ConversationContext:
    """세션별 대화 컨텍스트 관리"""
    
    def __init__(self):
        self.last_person: Optional[str] = None          # 마지막 언급된 사람
        self.last_client: Optional[str] = None          # 마지막 언급된 고객/병원
        self.last_topic: Optional[str] = None           # 마지막 주제
        self.last_time_period: Optional[str] = None     # 마지막 시간 표현
        self.last_metric: Optional[str] = None          # 마지막 지표
        self.last_agent: Optional[str] = None           # 마지막 사용 에이전트
        self.last_update: datetime = datetime.now()      # 마지막 업데이트 시간
        self.access_count: int = 0                       # 접근 횟수 (LRU용)
        
    def to_dict(self) -> Dict[str, Any]:
        """컨텍스트를 딕셔너리로 변환"""
        return {
            "last_person": self.last_person,
            "last_client": self.last_client,
            "last_topic": self.last_topic,
            "last_time_period": self.last_time_period,
            "last_metric": self.last_metric,
            "last_agent": self.last_agent,
            "last_update": self.last_update.isoformat(),
            "access_count": self.access_count
        }
    
    def from_dict(self, data: Dict[str, Any]):
        """딕셔너리에서 컨텍스트 복원"""
        self.last_person = data.get("last_person")
        self.last_client = data.get("last_client")
        self.last_topic = data.get("last_topic")
        self.last_time_period = data.get("last_time_period")
        self.last_metric = data.get("last_metric")
        self.last_agent = data.get("last_agent")
        self.last_update = datetime.fromisoformat(data.get("last_update", datetime.now().isoformat()))
        self.access_count = data.get("access_count", 0)


class AsyncContextManager:
    """비동기 대화 컨텍스트 관리자 (고도화 버전)"""
    
    def __init__(self, max_contexts: int = 1000, max_age_hours: int = 24):
        # LRU 캐시로 메모리 관리
        self.contexts: OrderedDict[str, ConversationContext] = OrderedDict()
        self.max_contexts = max_contexts
        self.max_age_hours = max_age_hours
        
        # 컨텍스트 접근을 위한 락
        self._lock = asyncio.Lock()
        
        # 자동 정리 태스크
        self._cleanup_task = None
        self._cleanup_interval = 3600  # 1시간마다 정리
        
        # 엔티티 추출 패턴
        self.patterns = {
            'person': r'([가-힣]{2,4})\s*(사원|직원|님|씨)?',
            'client': r'([가-힣]+병원|[가-힣]+의원|[가-힣]+약국|[A-Z]병원)',
            'time': r'(오늘|어제|이번\s*주|저번\s*주|이번\s*달|저번\s*달|작년|올해|[0-9]+월|[0-9]+년)',
            'metric': r'(실적|매출|판매량|목표|달성률|성과)'
        }
        
        # 주제 키워드 매핑
        self.topic_keywords = {
            'performance': ['실적', '매출', '성과', '목표', '달성'],
            'client': ['고객', '병원', '거래처', '약국', '의원'],
            'employee': ['직원', '사원', '인사', '조직', '부서'],
            'document': ['문서', '보고서', '양식', '서류', '계획서']
        }
        
        # 참조 표현 패턴
        self.reference_patterns = {
            'person_ref': [r'그\s*사람', r'해당\s*직원', r'그\s*직원', r'같은\s*사람'],
            'client_ref': [r'그\s*병원', r'해당\s*고객', r'그\s*거래처', r'같은\s*곳', r'거기'],
            'thing_ref': [r'그것', r'그거', r'것', r'그걸'],
            'time_ref': [r'그때', r'같은\s*기간', r'동일\s*기간']
        }
        
        # 컴파일된 패턴 (성능 향상)
        self._compiled_patterns = {
            key: re.compile(pattern, re.IGNORECASE) 
            for key, pattern in self.patterns.items()
        }
        
        self._compiled_ref_patterns = {
            key: [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
            for key, patterns in self.reference_patterns.items()
        }
    
    async def start_cleanup_task(self):
        """자동 정리 태스크 시작"""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._auto_cleanup())
            logger.info("Context cleanup task started")
    
    async def stop_cleanup_task(self):
        """자동 정리 태스크 중지"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
            logger.info("Context cleanup task stopped")
    
    async def _auto_cleanup(self):
        """주기적으로 오래된 컨텍스트 정리"""
        while True:
            try:
                await asyncio.sleep(self._cleanup_interval)
                await self.cleanup_old_contexts()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in auto cleanup: {e}")
    
    async def get_or_create_context(self, session_id: str) -> ConversationContext:
        """세션 컨텍스트 가져오기 또는 생성 (비동기)"""
        async with self._lock:
            if session_id in self.contexts:
                # LRU: 최근 사용으로 이동
                context = self.contexts.pop(session_id)
                context.access_count += 1
                self.contexts[session_id] = context
                return context
            else:
                # 새 컨텍스트 생성
                context = ConversationContext()
                self.contexts[session_id] = context
                
                # 최대 개수 초과 시 가장 오래된 것 제거
                if len(self.contexts) > self.max_contexts:
                    oldest_session = next(iter(self.contexts))
                    del self.contexts[oldest_session]
                    logger.info(f"Removed oldest context: {oldest_session}")
                
                return context
    
    async def extract_entities(self, query: str) -> Dict[str, Optional[str]]:
        """쿼리에서 엔티티 추출 (비동기)"""
        entities = {}
        
        # CPU 집약적 작업을 별도 스레드에서 실행
        loop = asyncio.get_event_loop()
        entities = await loop.run_in_executor(None, self._extract_entities_sync, query)
        
        logger.info(f"추출된 엔티티: {entities}")
        return entities
    
    def _extract_entities_sync(self, query: str) -> Dict[str, Optional[str]]:
        """동기 방식 엔티티 추출 (내부 사용)"""
        entities = {}
        
        # 컴파일된 패턴 사용 (성능 향상)
        for entity_type, pattern in self._compiled_patterns.items():
            match = pattern.search(query)
            if match:
                if entity_type in ['person', 'client', 'time', 'metric']:
                    entities[entity_type] = match.group(1)
        
        # 주제 판단
        for topic, keywords in self.topic_keywords.items():
            if any(keyword in query for keyword in keywords):
                entities['topic'] = topic
                break
        
        return entities
    
    async def resolve_references(self, query: str, context: ConversationContext) -> str:
        """참조 표현을 실제 값으로 해결 (비동기)"""
        # CPU 집약적 작업을 별도 스레드에서 실행
        loop = asyncio.get_event_loop()
        resolved_query = await loop.run_in_executor(
            None, self._resolve_references_sync, query, context
        )
        
        if resolved_query != query:
            logger.info(f"참조 해결: '{query}' -> '{resolved_query}'")
        
        return resolved_query
    
    def _resolve_references_sync(self, query: str, context: ConversationContext) -> str:
        """동기 방식 참조 해결 (내부 사용)"""
        resolved_query = query
        
        # 사람 참조 해결
        if context.last_person:
            for pattern in self._compiled_ref_patterns['person_ref']:
                resolved_query = pattern.sub(context.last_person, resolved_query)
        
        # 고객 참조 해결
        if context.last_client:
            for pattern in self._compiled_ref_patterns['client_ref']:
                resolved_query = pattern.sub(context.last_client, resolved_query)
        
        # "그것" 류 참조 해결
        for pattern in self._compiled_ref_patterns['thing_ref']:
            if pattern.search(resolved_query):
                # 마지막 주제와 관련 정보로 추론
                if context.last_topic == 'performance' and context.last_person:
                    replacement = f"{context.last_person}의 {context.last_metric or '실적'}"
                    resolved_query = pattern.sub(replacement, resolved_query)
                elif context.last_topic == 'client' and context.last_client:
                    replacement = f"{context.last_client} 정보"
                    resolved_query = pattern.sub(replacement, resolved_query)
        
        return resolved_query
    
    async def enhance_query(self, query: str, context: ConversationContext) -> str:
        """쿼리를 컨텍스트 기반으로 보완 (비동기)"""
        # CPU 집약적 작업을 별도 스레드에서 실행
        loop = asyncio.get_event_loop()
        enhanced = await loop.run_in_executor(
            None, self._enhance_query_sync, query, context
        )
        
        if enhanced != query:
            logger.info(f"쿼리 보완: '{query}' -> '{enhanced}'")
        
        return enhanced
    
    def _enhance_query_sync(self, query: str, context: ConversationContext) -> str:
        """동기 방식 쿼리 보완 (내부 사용)"""
        enhanced = query
        
        # 시간 표현만 있는 경우
        time_only_patterns = [r'^작년$', r'^올해$', r'^이번\s*달$', r'^저번\s*달$']
        for pattern in time_only_patterns:
            if re.match(pattern, query.strip()):
                if context.last_person and context.last_metric:
                    enhanced = f"{context.last_person}의 {query} {context.last_metric}"
                elif context.last_client and context.last_metric:
                    enhanced = f"{context.last_client}의 {query} {context.last_metric}"
                break
        
        # 사람 이름만 있는 경우
        person_only_match = re.match(r'^([가-힣]{2,4})\s*(사원|직원|님)?$', query.strip())
        if person_only_match and context.last_topic:
            person_name = person_only_match.group(1)
            if context.last_topic == 'performance':
                enhanced = f"{person_name}의 실적"
            elif context.last_metric:
                enhanced = f"{person_name}의 {context.last_metric}"
        
        return enhanced
    
    async def update_context(self, session_id: str, query: str, response: Optional[Dict] = None):
        """쿼리와 응답을 기반으로 컨텍스트 업데이트 (비동기)"""
        context = await self.get_or_create_context(session_id)
        
        # 엔티티 추출
        entities = await self.extract_entities(query)
        
        # 컨텍스트 업데이트
        async with self._lock:
            if entities.get('person'):
                context.last_person = entities['person']
            if entities.get('client'):
                context.last_client = entities['client']
            if entities.get('topic'):
                context.last_topic = entities['topic']
            if entities.get('time'):
                context.last_time_period = entities['time']
            if entities.get('metric'):
                context.last_metric = entities['metric']
                
            # 응답에서 에이전트 정보 업데이트
            if response and response.get('agent'):
                context.last_agent = response['agent']
                
            context.last_update = datetime.now()
        
        logger.info(f"컨텍스트 업데이트 완료: {context.to_dict()}")
    
    async def process_query(self, session_id: str, query: str) -> str:
        """쿼리 처리: 참조 해결 및 보완 (비동기)"""
        context = await self.get_or_create_context(session_id)
        
        # 1. 참조 해결
        resolved_query = await self.resolve_references(query, context)
        
        # 2. 쿼리 보완
        enhanced_query = await self.enhance_query(resolved_query, context)
        
        logger.info(f"쿼리 처리: '{query}' -> '{enhanced_query}'")
        return enhanced_query
    
    async def cleanup_old_contexts(self):
        """오래된 컨텍스트 정리 (비동기)"""
        async with self._lock:
            current_time = datetime.now()
            cutoff_time = current_time - timedelta(hours=self.max_age_hours)
            
            sessions_to_remove = []
            for session_id, context in self.contexts.items():
                if context.last_update < cutoff_time:
                    sessions_to_remove.append(session_id)
            
            for session_id in sessions_to_remove:
                del self.contexts[session_id]
                logger.info(f"Removed old context: {session_id}")
            
            if sessions_to_remove:
                logger.info(f"Cleaned up {len(sessions_to_remove)} old contexts")
    
    async def clear_context(self, session_id: str):
        """특정 세션의 컨텍스트 초기화 (비동기)"""
        async with self._lock:
            if session_id in self.contexts:
                del self.contexts[session_id]
                logger.info(f"세션 {session_id}의 컨텍스트 초기화")
    
    async def save_contexts_to_file(self, filepath: str):
        """컨텍스트를 파일로 저장 (백업용)"""
        async with self._lock:
            data = {
                session_id: context.to_dict()
                for session_id, context in self.contexts.items()
            }
        
        # 파일 쓰기를 별도 스레드에서 실행
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._save_to_file_sync, filepath, data)
    
    def _save_to_file_sync(self, filepath: str, data: Dict):
        """동기 방식 파일 저장 (내부 사용)"""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    async def load_contexts_from_file(self, filepath: str):
        """파일에서 컨텍스트 복원 (백업 복구용)"""
        # 파일 읽기를 별도 스레드에서 실행
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, self._load_from_file_sync, filepath)
        
        async with self._lock:
            self.contexts.clear()
            for session_id, context_data in data.items():
                context = ConversationContext()
                context.from_dict(context_data)
                self.contexts[session_id] = context
    
    def _load_from_file_sync(self, filepath: str) -> Dict:
        """동기 방식 파일 읽기 (내부 사용)"""
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def get_stats(self) -> Dict[str, Any]:
        """컨텍스트 관리 통계"""
        return {
            "total_contexts": len(self.contexts),
            "max_contexts": self.max_contexts,
            "max_age_hours": self.max_age_hours,
            "cleanup_interval": self._cleanup_interval
        }


# 싱글톤 인스턴스 (비동기 버전)
context_manager = AsyncContextManager()

# 하위 호환성을 위한 동기 래퍼 클래스
class ContextManager:
    """기존 코드와의 호환성을 위한 동기 래퍼"""
    
    def __init__(self):
        self.async_manager = context_manager
    
    def get_or_create_context(self, session_id: str) -> ConversationContext:
        """동기 방식으로 컨텍스트 가져오기"""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                self.async_manager.get_or_create_context(session_id)
            )
        finally:
            loop.close()
    
    def process_query(self, session_id: str, query: str) -> str:
        """동기 방식으로 쿼리 처리"""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                self.async_manager.process_query(session_id, query)
            )
        finally:
            loop.close()
    
    def update_context(self, session_id: str, query: str, response: Optional[Dict] = None):
        """동기 방식으로 컨텍스트 업데이트"""
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                self.async_manager.update_context(session_id, query, response)
            )
        finally:
            loop.close()
    
    def clear_context(self, session_id: str):
        """동기 방식으로 컨텍스트 초기화"""
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                self.async_manager.clear_context(session_id)
            )
        finally:
            loop.close()

# 하위 호환성을 위한 동기 인스턴스
sync_context_manager = ContextManager()