"""
Docs Agent 웹 인터페이스
대화형 문서 생성을 위한 웹 기반 인터페이스
"""
from typing import Dict, Any, Optional
import uuid
from .create_document_agent import CreateDocumentAgent, State
from langchain_core.messages import HumanMessage
import logging

logger = logging.getLogger(__name__)

class WebDocumentAgent:
    """웹 기반 대화형 문서 생성 에이전트"""
    
    def __init__(self):
        self.agent = CreateDocumentAgent()
        self.sessions: Dict[str, Dict[str, Any]] = {}  # 세션별 상태 저장
        
    def create_session(self, session_id: str, initial_query: str) -> Dict[str, Any]:
        """새 세션 생성 및 초기화"""
        thread_id = str(uuid.uuid4())
        
        # 초기 상태 생성
        initial_state = {
            "messages": [HumanMessage(content=initial_query)],
            "doc_type": None,
            "template_content": None,
            "filled_data": None,
            "violation": None,
            "final_doc": None,
            "retry_count": 0,
            "restart_classification": None,
            "classification_retry_count": None,
            "classification_failed": None,
            "skip_verification": None,
            "end_process": None,
            "parse_retry_count": None,
            "parse_failed": None,
            "user_reply": None,
            "verification_reply": None,
            "verification_result": None
        }
        
        # 세션 정보 저장
        self.sessions[session_id] = {
            "thread_id": thread_id,
            "state": initial_state,
            "current_step": "classification",
            "waiting_for_input": False,
            "input_type": None
        }
        
        # 첫 단계 실행 (문서 분류)
        return self._execute_step(session_id)
        
    def process_user_input(self, session_id: str, user_input: str) -> Dict[str, Any]:
        """사용자 입력 처리"""
        if session_id not in self.sessions:
            return {
                "success": False,
                "error": "세션을 찾을 수 없습니다."
            }
            
        session = self.sessions[session_id]
        
        if not session.get("waiting_for_input"):
            return {
                "success": False,
                "error": "사용자 입력을 기다리고 있지 않습니다."
            }
            
        # 입력 타입에 따라 상태 업데이트
        input_type = session.get("input_type")
        state = session["state"]
        
        if input_type == "verification":
            state["verification_reply"] = user_input
        elif input_type == "manual_selection":
            state["user_reply"] = user_input
            # 수동 선택의 경우 verification_reply에도 저장 (receive_manual_doc_type_input이 이것을 확인함)
            state["verification_reply"] = user_input
            # process_manual_doc_type_selection을 위해 messages에도 추가
            state["messages"].append(HumanMessage(content=user_input))
        elif input_type == "data_input":
            state["user_reply"] = user_input
            # 데이터 입력의 경우 messages에도 추가
            state["messages"].append(HumanMessage(content=user_input))
        else:
            state["user_reply"] = user_input
            
        session["waiting_for_input"] = False
        session["input_type"] = None
        
        # 다음 단계 실행
        return self._execute_step(session_id)
        
    def _execute_step(self, session_id: str) -> Dict[str, Any]:
        """현재 단계 실행"""
        session = self.sessions[session_id]
        state = session["state"]
        current_step = session["current_step"]
        
        try:
            if current_step == "classification":
                # 문서 분류
                new_state = self.agent.classify_doc_type(state)
                session["state"] = new_state
                
                # 분류 검증이 필요한지 확인
                if new_state.get("doc_type") and not new_state.get("classification_failed"):
                    session["current_step"] = "verification"
                    session["waiting_for_input"] = True
                    session["input_type"] = "verification"
                    
                    return {
                        "success": True,
                        "step": "verification",
                        "message": f"'{new_state['doc_type']}'로 분류되었습니다. 맞으신가요? (예/아니오)",
                        "doc_type": new_state["doc_type"],
                        "waiting_for_input": True,
                        "input_type": "verification"
                    }
                else:
                    # 분류 실패 시 수동 선택
                    session["current_step"] = "manual_selection"
                    session["waiting_for_input"] = True
                    session["input_type"] = "manual_selection"
                    
                    return {
                        "success": True,
                        "step": "manual_selection",
                        "message": "문서 타입을 자동으로 분류할 수 없습니다. 다음 중 선택해주세요:",
                        "options": [
                            "1. 영업방문 결과보고서",
                            "2. 제품설명회 시행 신청서",
                            "3. 제품설명회 시행 결과보고서"
                        ],
                        "waiting_for_input": True,
                        "input_type": "manual_selection"
                    }
                    
            elif current_step == "verification":
                # 검증 응답 처리
                new_state = self.agent.receive_verification_input(state)
                session["state"] = new_state
                
                if new_state.get("verification_result") == "긍정":
                    # 데이터 수집으로 바로 진행 (템플릿은 이미 로드됨)
                    session["current_step"] = "data_collection"
                    session["waiting_for_input"] = True
                    session["input_type"] = "data_input"
                    
                    # 필요한 정보 안내
                    template_guide = self._get_template_guide(new_state["doc_type"])
                    
                    return {
                        "success": True,
                        "step": "data_collection",
                        "message": f"{new_state['doc_type']} 작성을 시작합니다.\n{template_guide}",
                        "template": new_state["template_content"],
                        "waiting_for_input": True,
                        "input_type": "data_input"
                    }
                else:
                    # 재분류 또는 수동 선택
                    session["current_step"] = "manual_selection"
                    session["waiting_for_input"] = True
                    session["input_type"] = "manual_selection"
                    
                    return {
                        "success": True,
                        "step": "manual_selection",
                        "message": "다시 선택해주세요:",
                        "options": [
                            "1. 영업방문 결과보고서",
                            "2. 제품설명회 시행 신청서",
                            "3. 제품설명회 시행 결과보고서"
                        ],
                        "waiting_for_input": True,
                        "input_type": "manual_selection"
                    }
                    
            elif current_step == "manual_selection":
                # 수동 선택 처리
                new_state = self.agent.receive_manual_doc_type_input(state)
                session["state"] = new_state
                
                # process_manual_doc_type_selection 호출 필요
                new_state = self.agent.process_manual_doc_type_selection(new_state)
                session["state"] = new_state
                
                if new_state.get("template_content"):
                    session["current_step"] = "data_collection"
                    session["waiting_for_input"] = True
                    session["input_type"] = "data_input"
                    
                    # 필요한 정보 안내
                    template_guide = self._get_template_guide(new_state["doc_type"])
                    
                    return {
                        "success": True,
                        "step": "data_collection",
                        "message": f"{new_state['doc_type']} 작성을 시작합니다.\n{template_guide}",
                        "template": new_state["template_content"],
                        "waiting_for_input": True,
                        "input_type": "data_input"
                    }
                else:
                    return {
                        "success": False,
                        "error": "문서 타입 선택에 실패했습니다."
                    }
                
            elif current_step == "data_collection":
                # 사용자 입력 파싱
                new_state = self.agent.parse_user_input(state)
                session["state"] = new_state
                
                if new_state.get("filled_data"):
                    # 문서 생성으로 진행
                    session["current_step"] = "document_generation"
                    return self._execute_step(session_id)
                else:
                    # 파싱 실패 시 재입력 요청
                    session["waiting_for_input"] = True
                    session["input_type"] = "data_input"
                    
                    return {
                        "success": True,
                        "step": "data_collection",
                        "message": "입력 정보를 파싱할 수 없습니다. 다시 입력해주세요.",
                        "waiting_for_input": True,
                        "input_type": "data_input"
                    }
                    
            elif current_step == "document_generation":
                # 문서 생성
                new_state = self.agent.create_choan_document(state)
                session["state"] = new_state
                
                if new_state.get("final_doc"):
                    # 완료
                    session["current_step"] = "completed"
                    return {
                        "success": True,
                        "step": "completed",
                        "message": "문서가 성공적으로 생성되었습니다!",
                        "document": new_state["final_doc"],
                        "doc_type": new_state["doc_type"],
                        "file_path": new_state.get("file_path")
                    }
                else:
                    return {
                        "success": False,
                        "error": "문서 생성에 실패했습니다."
                    }
                    
            else:
                return {
                    "success": False,
                    "error": f"알 수 없는 단계: {current_step}"
                }
                
        except Exception as e:
            logger.error(f"단계 실행 오류: {e}")
            return {
                "success": False,
                "error": str(e)
            }
            
    def _get_template_guide(self, doc_type: str) -> str:
        """문서 타입별 입력 가이드"""
        guides = {
            "영업방문 결과보고서": """
필요한 정보를 입력해주세요:
- 방문일자
- 방문자
- 방문기관
- 면담자
- 방문목적
- 면담내용
- 경쟁사 정보 (선택)
- 건의사항 (선택)
""",
            "제품설명회 시행 신청서": """
필요한 정보를 입력해주세요:
- 신청일자
- 신청자
- 소속
- 행사명
- 행사일시
- 행사장소
- 참석대상 및 인원
- 행사목적
- 지원요청사항
""",
            "제품설명회 시행 결과보고서": """
필요한 정보를 입력해주세요:
- 보고일자
- 보고자
- 소속
- 행사명
- 행사일시
- 행사장소
- 참석인원
- 행사내용
- 주요성과
- 향후계획
"""
        }
        
        return guides.get(doc_type, "필요한 정보를 입력해주세요.")
        
    def get_session_status(self, session_id: str) -> Dict[str, Any]:
        """세션 상태 조회"""
        if session_id not in self.sessions:
            return {
                "success": False,
                "error": "세션을 찾을 수 없습니다."
            }
            
        session = self.sessions[session_id]
        return {
            "success": True,
            "current_step": session["current_step"],
            "waiting_for_input": session["waiting_for_input"],
            "input_type": session["input_type"],
            "doc_type": session["state"].get("doc_type")
        }

# 싱글톤 인스턴스
web_agent = WebDocumentAgent()