"""
멀티턴 대화를 위한 컨텍스트 유틸리티
모든 에이전트가 공통으로 사용하는 대화 기록 분석 기능
"""
import re
from typing import List, Dict, Optional, Tuple, Any
import logging

logger = logging.getLogger(__name__)


class ContextAnalyzer:
    """대화 기록 분석 및 참조 해결"""
    
    def __init__(self):
        # 참조 패턴 정의
        self.person_refs = ["그 사람", "그 직원", "같은 사람", "해당 직원", "그분"]
        self.client_refs = ["그 병원", "그 거래처", "같은 병원", "해당 거래처", "그곳"]
        self.time_refs = ["작년", "지난달", "이번달", "다음달", "올해"]
        
    def analyze_messages(self, messages: List[Dict]) -> Dict[str, Any]:
        """대화 기록 분석하여 컨텍스트 추출"""
        context = {
            "last_person": None,
            "last_client": None,
            "last_time_period": None,
            "last_topic": None,
            "entities": []
        }
        
        if not messages:
            return context
            
        # 역순으로 탐색 (최근 대화가 더 중요)
        for msg in reversed(messages[-10:]):  # 최근 10개만 분석
            content = msg.get("content", "")
            role = msg.get("role", "")
            
            # 사람 이름 추출
            person = self._extract_person_name(content)
            if person and not context["last_person"]:
                context["last_person"] = person
                
            # 거래처/병원 이름 추출
            client = self._extract_client_name(content)
            if client and not context["last_client"]:
                context["last_client"] = client
                
            # 시간 정보 추출
            time_period = self._extract_time_period(content)
            if time_period and not context["last_time_period"]:
                context["last_time_period"] = time_period
                
        return context
    
    def resolve_references(self, query: str, messages: List[Dict]) -> str:
        """쿼리의 참조 표현을 실제 값으로 변환"""
        context = self.analyze_messages(messages)
        resolved_query = query
        
        # 사람 참조 해결
        if context["last_person"]:
            for ref in self.person_refs:
                if ref in resolved_query:
                    resolved_query = resolved_query.replace(ref, context["last_person"])
                    logger.info(f"참조 해결: '{ref}' → '{context['last_person']}'")
                    
        # 거래처 참조 해결
        if context["last_client"]:
            for ref in self.client_refs:
                if ref in resolved_query:
                    resolved_query = resolved_query.replace(ref, context["last_client"])
                    logger.info(f"참조 해결: '{ref}' → '{context['last_client']}'")
                    
        # 시간 참조 해결
        resolved_query = self._resolve_time_references(resolved_query, context)
        
        return resolved_query
    
    def _extract_person_name(self, text: str) -> Optional[str]:
        """텍스트에서 사람 이름 추출"""
        # 직원 패턴
        patterns = [
            r'(\w{2,4})\s*직원',
            r'(\w{2,4})\s*님',
            r'직원\s*(\w{2,4})',
            r'(\w{2,4})\s*사원',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
                
        # 일반적인 한국 이름 패턴 (2-4글자)
        korean_name = re.search(r'[가-힣]{2,4}(?=\s|의|님|씨)', text)
        if korean_name:
            name = korean_name.group(0)
            # 제외할 단어들
            exclude = ['실적', '매출', '분석', '조회', '검색', '거래처', '병원', '약국']
            if name not in exclude:
                return name
                
        return None
    
    def _extract_client_name(self, text: str) -> Optional[str]:
        """텍스트에서 거래처/병원 이름 추출"""
        patterns = [
            r'(\w+의원)',
            r'(\w+병원)',
            r'(\w+약국)',
            r'(\w+제약)',
            r'(\w+메디칼)',
            r'(\w+클리닉)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
                
        return None
    
    def _extract_time_period(self, text: str) -> Optional[str]:
        """텍스트에서 시간 정보 추출"""
        # YYYYMM 형식
        yyyymm = re.search(r'(20\d{2})(0[1-9]|1[0-2])', text)
        if yyyymm:
            return yyyymm.group(0)
            
        # YYYY년 MM월 형식
        year_month = re.search(r'(20\d{2})년\s*(\d{1,2})월', text)
        if year_month:
            year = year_month.group(1)
            month = year_month.group(2).zfill(2)
            return f"{year}{month}"
            
        # 상대적 시간 표현은 나중에 처리
        return None
    
    def _resolve_time_references(self, query: str, context: Dict) -> str:
        """시간 관련 참조 해결"""
        from datetime import datetime, timedelta
        
        now = datetime.now()
        resolved = query
        
        # 작년
        if "작년" in query:
            last_year = now.year - 1
            if "실적" in query or "매출" in query:
                resolved = resolved.replace("작년", f"{last_year}년")
                
        # 지난달
        if "지난달" in query:
            last_month = now - timedelta(days=30)
            resolved = resolved.replace("지난달", f"{last_month.year}년 {last_month.month}월")
            
        # 이번달
        if "이번달" in query:
            resolved = resolved.replace("이번달", f"{now.year}년 {now.month}월")
            
        # 올해
        if "올해" in query:
            resolved = resolved.replace("올해", f"{now.year}년")
            
        return resolved
    
    def get_conversation_summary(self, messages: List[Dict], max_messages: int = 5) -> str:
        """최근 대화 요약"""
        if not messages:
            return ""
            
        recent = messages[-max_messages:]
        summary_parts = []
        
        for msg in recent:
            role = "사용자" if msg.get("role") == "user" else "AI"
            content = msg.get("content", "")[:100]  # 100자까지만
            summary_parts.append(f"{role}: {content}")
            
        return "\n".join(summary_parts)


# 싱글톤 인스턴스
context_analyzer = ContextAnalyzer()


# 편의 함수들
def resolve_references(query: str, messages: List[Dict] = None) -> str:
    """참조 해결 편의 함수"""
    return context_analyzer.resolve_references(query, messages or [])


def analyze_context(messages: List[Dict] = None) -> Dict[str, Any]:
    """컨텍스트 분석 편의 함수"""
    return context_analyzer.analyze_messages(messages or [])


def get_last_mentioned_person(messages: List[Dict] = None) -> Optional[str]:
    """마지막으로 언급된 사람 이름"""
    context = analyze_context(messages)
    return context.get("last_person")


def get_last_mentioned_client(messages: List[Dict] = None) -> Optional[str]:
    """마지막으로 언급된 거래처"""
    context = analyze_context(messages)
    return context.get("last_client")