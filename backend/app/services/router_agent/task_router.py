"""
통합 태스크 라우터
단일/멀티 태스크를 구분하지 않고 통합 처리
"""
import os
import json
import logging
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from openai import AsyncOpenAI
from pathlib import Path
from dotenv import load_dotenv

from .router_agent import RouterAgent, AVAILABLE_AGENT_IDS
from .prompts import get_task_decomposition_prompt
from ..common.handlers import agent_handlers

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# .env 파일 로드
env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
    logger.info(f"Loaded .env from: {env_path}")


class TaskRouter:
    """통합 태스크 라우터"""
    
    def __init__(self):
        self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.router_agent = RouterAgent()  # 기존 라우터 활용
        self.agent_handlers = agent_handlers
        
    async def process_query(self, query: str, session_id: str, messages: List[Dict] = None) -> Dict[str, Any]:
        """
        사용자 쿼리를 처리하는 메인 메서드
        
        Args:
            query: 사용자 입력
            session_id: 세션 ID
            messages: 이전 대화 기록
            
        Returns:
            처리 결과
        """
        try:
            # 1. 태스크 분해
            tasks = await self._decompose_query(query)
            
            if not tasks:
                # 에이전트가 필요없는 일반 대화
                return {
                    "type": "general",
                    "response": "안녕하세요! 무엇을 도와드릴까요?",
                    "tasks": []
                }
            
            # 2. docs_agent가 포함되어 있는지 확인
            has_docs_agent = any(task.get("agent") in ["docs_agent", "create_document_agent"] for task in tasks)
            
            # 3. 실행 계획 수립
            execution_plan = self._create_execution_plan(tasks)
            
            # 4. 태스크 실행
            if len(tasks) == 1:
                # 단일 태스크
                result = await self._execute_single_task(tasks[0], session_id, messages)
                return {
                    "type": "single",
                    "response": result,
                    "tasks": tasks
                }
            else:
                # 멀티 태스크인데 docs_agent가 포함된 경우
                if has_docs_agent:
                    # docs_agent는 대화형이므로 멀티 태스크로 처리하면 안됨
                    # 다른 태스크들만 먼저 처리하고 docs_agent는 별도 안내
                    non_docs_tasks = [t for t in tasks if t.get("agent") not in ["docs_agent", "create_document_agent"]]
                    docs_tasks = [t for t in tasks if t.get("agent") in ["docs_agent", "create_document_agent"]]
                    
                    if non_docs_tasks:
                        # docs_agent가 아닌 태스크들만 실행
                        results = await self._execute_multi_tasks(non_docs_tasks, self._create_execution_plan(non_docs_tasks), session_id, messages)
                        aggregated = self._aggregate_results(results, non_docs_tasks)
                        
                        # docs_agent는 별도로 안내
                        if docs_tasks:
                            aggregated["summary"] += f"\n\n📝 문서 생성은 대화형 작업이므로 별도로 진행해주세요:\n"
                            for task in docs_tasks:
                                aggregated["summary"] += f"- {task['description']}\n"
                        
                        return {
                            "type": "multi",
                            "response": aggregated,
                            "tasks": non_docs_tasks,
                            "detailed_results": results,
                            "execution_plan": self._create_execution_plan(non_docs_tasks),
                            "pending_docs_tasks": docs_tasks
                        }
                    else:
                        # 모든 태스크가 docs_agent인 경우
                        return {
                            "type": "docs_only",
                            "response": "문서 생성은 대화형 작업입니다. 각 문서를 개별적으로 생성해주세요.",
                            "tasks": docs_tasks
                        }
                else:
                    # docs_agent가 없는 일반 멀티 태스크
                    results = await self._execute_multi_tasks(tasks, execution_plan, session_id, messages)
                    aggregated = self._aggregate_results(results, tasks)
                    return {
                        "type": "multi",
                        "response": aggregated,  # 이제 구조화된 객체
                        "tasks": tasks,
                        "detailed_results": results,
                        "execution_plan": execution_plan
                    }
                
        except Exception as e:
            logger.error(f"Task routing failed: {e}")
            raise
    
    async def _decompose_query(self, query: str) -> List[Dict]:
        """쿼리를 태스크들로 분해"""
        try:
            prompt = get_task_decomposition_prompt(query)
            
            response = await self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a task decomposition expert. Always respond with valid JSON only, no code blocks."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1
            )
            
            # 응답 내용 가져오기
            response_content = response.choices[0].message.content
            logger.debug(f"GPT Response: {response_content}")
            
            # JSON 파싱 (코드 블록 제거)
            if "```json" in response_content:
                response_content = response_content.split("```json")[1].split("```")[0]
            elif "```" in response_content:
                response_content = response_content.split("```")[1].split("```")[0]
            
            # 전후 공백 제거 후 파싱
            result = json.loads(response_content.strip())
            tasks = result.get("tasks", [])
            
            logger.info(f"Query decomposed into {len(tasks)} tasks")
            return tasks
            
        except Exception as e:
            logger.error(f"Task decomposition failed: {e}")
            # Fallback: 전체를 하나의 태스크로 처리
            return [{
                "id": 0,
                "description": query,
                "agent": await self.router_agent.classify(query, []),
                "query": query,
                "depends_on": [],
                "parallel_group": 0
            }]
    
    def _create_execution_plan(self, tasks: List[Dict]) -> Dict[str, List[int]]:
        """실행 계획 수립 (병렬/순차 그룹핑)"""
        plan = {}
        
        for task in tasks:
            group = task.get("parallel_group", 0)
            if group not in plan:
                plan[group] = []
            plan[group].append(task["id"])
            
        return plan
    
    async def _execute_single_task(self, task: Dict, session_id: str, messages: List[Dict]) -> str:
        """단일 태스크 실행"""
        agent_name = task["agent"]
        query = task["query"]
        
        # 에이전트 핸들러 가져오기
        if agent_name not in self.agent_handlers:
            logger.error(f"Unknown agent: {agent_name}")
            return f"죄송합니다. {agent_name} 에이전트를 찾을 수 없습니다."
            
        handler = self.agent_handlers[agent_name]
        
        try:
            # 에이전트 실행 - 에이전트별로 다른 인자 처리
            if agent_name in ["employee_agent", "client_agent"]:
                # 3개 인자를 받는 에이전트
                result = await handler(query, session_id, messages or [])
            else:
                # 2개 인자만 받는 에이전트 (search_agent, docs_agent)
                result = await handler(query, session_id)
            return result
        except Exception as e:
            logger.error(f"Agent execution failed: {agent_name} - {e}")
            return f"처리 중 오류가 발생했습니다: {str(e)}"
    
    async def _execute_multi_tasks(self, tasks: List[Dict], execution_plan: Dict[str, List[int]], 
                                   session_id: str, messages: List[Dict]) -> Dict[int, Any]:
        """멀티 태스크 실행"""
        results = {}
        task_map = {task["id"]: task for task in tasks}
        
        # 그룹별로 순차 실행
        for group_num in sorted(execution_plan.keys()):
            group_tasks = execution_plan[group_num]
            
            # 그룹 내 태스크들은 병렬 실행
            group_results = await asyncio.gather(*[
                self._execute_task_with_context(
                    task_map[task_id], 
                    results, 
                    session_id, 
                    messages
                )
                for task_id in group_tasks
            ])
            
            # 결과 저장
            for task_id, result in zip(group_tasks, group_results):
                results[task_id] = result
                
        return results
    
    async def _execute_task_with_context(self, task: Dict, previous_results: Dict[int, Any],
                                       session_id: str, messages: List[Dict]) -> Any:
        """이전 결과를 참고하여 태스크 실행"""
        # 의존성이 있는 경우 이전 결과를 쿼리에 추가
        enhanced_query = task["query"]
        
        if task.get("depends_on"):
            context_parts = []
            for dep_id in task["depends_on"]:
                if dep_id in previous_results:
                    context_parts.append(f"[이전 분석 결과 {dep_id}]: {previous_results[dep_id]}")
            
            if context_parts:
                enhanced_query = "\n".join(context_parts) + "\n\n" + enhanced_query
        
        # 태스크 실행
        modified_task = task.copy()
        modified_task["query"] = enhanced_query
        
        return await self._execute_single_task(modified_task, session_id, messages)
    
    def _aggregate_results(self, results: Dict[int, Any], tasks: List[Dict]) -> Dict[str, Any]:
        """멀티 태스크 결과를 구조화된 형태로 반환"""
        if not results:
            return {
                "summary": "요청을 처리할 수 없습니다.",
                "steps": []
            }
            
        # 태스크 순서대로 결과 정리
        steps = []
        summary_parts = []
        
        for task in sorted(tasks, key=lambda x: x["id"]):
            task_id = task["id"]
            if task_id in results:
                step_info = {
                    "step": task_id + 1,
                    "agent": task["agent"],
                    "description": task["description"],
                    "status": "completed",
                    "result": results[task_id]
                }
                steps.append(step_info)
                summary_parts.append(f"✅ {task['description']}")
                
        # 전체 요약
        summary = "모든 작업이 완료되었습니다.\n\n" + "\n".join(summary_parts)
        
        return {
            "summary": summary,
            "steps": steps,
            "total_steps": len(tasks),
            "completed_steps": len(steps)
        }


# 싱글톤 인스턴스
task_router = TaskRouter()