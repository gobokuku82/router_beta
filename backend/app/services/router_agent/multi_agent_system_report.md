# 멀티 에이전트 실행 시스템 상세 보고서

작성일: 2025-01-31

## 📌 시스템 개요

멀티 에이전트 실행 시스템은 사용자의 복합적인 요청을 분석하여 여러 에이전트를 조합해 처리하는 고도화된 시스템입니다.

### 핵심 특징
- **통합 처리**: 단일/멀티 태스크를 하나의 파이프라인으로 처리
- **지능적 분해**: GPT-4를 활용한 태스크 자동 분해
- **의존성 관리**: 태스크 간 순서와 데이터 전달 자동화
- **병렬 처리**: 독립적인 태스크들의 동시 실행

## 🏗️ 시스템 아키텍처

```
┌─────────────────┐
│  사용자 요청     │
└────────┬────────┘
         │
┌────────▼────────┐
│ /api/chat/multi │ (router_api.py)
└────────┬────────┘
         │
┌────────▼────────┐
│  TaskRouter     │ (task_router.py)
└────────┬────────┘
         │
    ┌────┴────┬─────────┬──────────┐
    │         │         │          │
┌───▼──┐ ┌───▼──┐ ┌────▼────┐ ┌───▼──┐
│Agent1│ │Agent2│ │Agent3   │ │Agent4│
└──────┘ └──────┘ └─────────┘ └──────┘
```

## 📁 파일 구조 및 기능

### 1. **prompts/task_decomposition.py**

#### 목적
사용자 쿼리를 분석하여 실행 가능한 태스크들로 분해하는 프롬프트 관리

#### 주요 구성요소
```python
TASK_DECOMPOSITION_PROMPT = """
# GPT-4에게 전달되는 프롬프트
# 쿼리를 JSON 형식의 태스크 리스트로 변환
"""

def get_task_decomposition_prompt(query: str) -> str:
    """프롬프트 생성 함수"""
```

#### 출력 형식
```json
{
    "tasks": [
        {
            "id": 0,
            "description": "태스크 설명",
            "agent": "사용할 에이전트",
            "query": "에이전트에 전달할 쿼리",
            "depends_on": [],  // 의존성
            "parallel_group": 0  // 병렬 그룹
        }
    ],
    "execution_strategy": "sequential|parallel|mixed"
}
```

### 2. **task_router.py**

#### 클래스: TaskRouter

##### 초기화
```python
def __init__(self):
    self.client = AsyncOpenAI()  # GPT-4 클라이언트
    self.router_agent = RouterAgent()  # 기존 라우터 재활용
    self.agent_handlers = agent_handlers  # 에이전트 실행 함수들
```

##### 핵심 메서드

###### 1. process_query()
```python
async def process_query(self, query: str, session_id: str, messages: List[Dict]) -> Dict
```
- **역할**: 메인 진입점, 전체 처리 흐름 관리
- **처리 과정**:
  1. 태스크 분해 (_decompose_query)
  2. 실행 계획 수립 (_create_execution_plan)
  3. 단일/멀티 분기 처리
  4. 결과 반환

###### 2. _decompose_query()
```python
async def _decompose_query(self, query: str) -> List[Dict]
```
- **역할**: GPT-4를 사용해 쿼리를 태스크로 분해
- **입력**: "거래처 분석하고 보고서 작성해줘"
- **출력**: [{task1}, {task2}] 형태의 태스크 리스트

###### 3. _create_execution_plan()
```python
def _create_execution_plan(self, tasks: List[Dict]) -> Dict[str, List[int]]
```
- **역할**: 병렬 실행 그룹 생성
- **출력 예시**:
```python
{
    0: [0, 1],  # 그룹 0: 태스크 0,1 병렬 실행
    1: [2]      # 그룹 1: 태스크 2 순차 실행
}
```

###### 4. _execute_single_task()
```python
async def _execute_single_task(self, task: Dict, session_id: str, messages: List[Dict]) -> str
```
- **역할**: 단일 태스크 실행
- **처리**: 에이전트 핸들러 호출 및 에러 처리

###### 5. _execute_multi_tasks()
```python
async def _execute_multi_tasks(self, tasks: List[Dict], execution_plan: Dict, 
                              session_id: str, messages: List[Dict]) -> Dict[int, Any]
```
- **역할**: 멀티 태스크 실행 오케스트레이션
- **특징**:
  - 그룹별 순차 실행
  - 그룹 내 병렬 실행 (asyncio.gather)
  - 의존성 있는 태스크에 이전 결과 전달

###### 6. _execute_task_with_context()
```python
async def _execute_task_with_context(self, task: Dict, previous_results: Dict[int, Any],
                                   session_id: str, messages: List[Dict]) -> Any
```
- **역할**: 의존성 처리 및 컨텍스트 전달
- **처리**: depends_on 태스크들의 결과를 현재 쿼리에 추가

###### 7. _aggregate_results()
```python
def _aggregate_results(self, results: Dict[int, Any], tasks: List[Dict]) -> str
```
- **역할**: 멀티 태스크 결과 통합
- **출력**: 마크다운 형식의 통합 결과

### 3. **router_api.py 수정사항**

#### 새로운 엔드포인트
```python
@router.post("/chat/multi")
async def multi_task_chat(req: QueryRequest)
```

#### 처리 흐름
1. 세션 관리
2. 메시지 저장 (chat_history)
3. 컨텍스트 로드 (이전 대화)
4. 컨텍스트 매니저 적용 (참조 해결)
5. TaskRouter 호출
6. 결과 저장 및 반환

## 🔄 데이터 흐름

### 1. 단일 태스크 플로우
```
사용자: "김철수 실적 조회"
    ↓
TaskRouter._decompose_query()
    ↓
[{task: "김철수 실적 조회", agent: "employee_agent"}]
    ↓
_execute_single_task()
    ↓
employee_agent 실행
    ↓
결과 반환
```

### 2. 멀티 태스크 플로우
```
사용자: "거래처 분석하고 보고서 작성해줘"
    ↓
TaskRouter._decompose_query()
    ↓
[
  {id: 0, task: "거래처 분석", agent: "client_agent"},
  {id: 1, task: "보고서 작성", agent: "docs_agent", depends_on: [0]}
]
    ↓
_create_execution_plan()
    ↓
{0: [0], 1: [1]}  // 순차 실행
    ↓
_execute_multi_tasks()
    ├─ 그룹 0: client_agent 실행
    └─ 그룹 1: docs_agent 실행 (0번 결과 포함)
    ↓
_aggregate_results()
    ↓
통합 결과 반환
```

## 🔗 상태(State) 전달 메커니즘

### 1. **세션 상태**
- `session_id`: 대화 세션 식별자
- `messages`: 이전 대화 기록
- 모든 함수 호출 시 전달

### 2. **태스크 간 상태 전달**
```python
# depends_on을 통한 의존성 명시
{
    "id": 2,
    "depends_on": [0, 1],  # 0, 1번 태스크 결과 필요
    ...
}

# _execute_task_with_context에서 처리
if task.get("depends_on"):
    # 이전 결과를 쿼리에 추가
    enhanced_query = previous_results + original_query
```

### 3. **컨텍스트 매니저 통합**
- 원본 쿼리 → 보완된 쿼리 변환
- "그 사람" → "김철수" 같은 참조 해결
- sync_context_manager 사용 (동기 호환성)

### 4. **결과 저장 및 추적**
```python
# 각 태스크 결과 저장
save_message(session_id, "assistant", response, {
    "type": "multi",
    "tasks": tasks,
    "detailed_results": results
})
```

## 🚀 사용 예시

### API 호출
```bash
POST /api/chat/multi
{
    "session_id": "session_123",
    "query": "미라클의원 거래처 분석하고 영업 실적 분석한 다음 방문보고서 작성해줘"
}
```

### 응답 형태
```json
{
    "success": true,
    "response": "## 미라클의원 거래처 분석\n...\n\n## 영업 실적 분석\n...\n\n## 방문보고서\n...",
    "type": "multi",
    "tasks": [...],
    "detailed_results": {
        "0": "거래처 분석 결과...",
        "1": "실적 분석 결과...",
        "2": "보고서 내용..."
    }
}
```

## 🔧 확장 포인트

1. **새로운 에이전트 추가**
   - handlers.py에 핸들러 등록
   - task_decomposition 프롬프트 업데이트

2. **실행 전략 추가**
   - 조건부 실행
   - 반복 실행
   - 실패 시 대체 경로

3. **성능 최적화**
   - 캐싱 메커니즘
   - 태스크 우선순위
   - 리소스 제한

## 📊 시스템 장점

1. **유연성**: 단일/멀티 통합 처리
2. **확장성**: 새로운 패턴 쉽게 추가
3. **효율성**: 병렬 처리로 성능 향상
4. **추적성**: 각 단계별 로깅 및 저장
5. **호환성**: 기존 시스템과 완벽 호환