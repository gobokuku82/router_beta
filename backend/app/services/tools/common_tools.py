from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from typing import Annotated
import requests
import json
from dotenv import load_dotenv

load_dotenv()

@tool
def check_policy_violation(content: Annotated[str, "작성된 문서 본문"]) -> str:
    """작성된 문서 내용이 회사 규정을 위반하는지 LLM과 OpenSearch를 통해 검사합니다."""
    
    try:
        # 1단계: LLM을 사용해 규정 확인이 필요한 문구 추출
        llm = ChatOpenAI(model="gpt-4o", temperature=0.7)
        
        extraction_prompt = ChatPromptTemplate.from_messages([
            ("system", """
아래 규칙을 지키면서 행위 단위로 판단 가능한 문구들을 추출해주세요.

- 행위 단위란 시간, 장소, 인물, 행위, 목적, 결과, 비용 등이 하나의 사건처럼 묶여 기술된 문장 또는 절을 의미합니다.
- 고객정보, 담당자, 방문자 같은 개인정보 내용은 판단 대상에서 제외하세요.
- 문장은 자연스러운 단위로 하나의 행위를 기준으로 나누되, 너무 잘게 쪼개지 말고 규정 위반 여부를 판단할 수 있을 정도의 정보량을 갖추도록 하세요.
- 반드시 결과를 JSON 문자열 배열 형식으로 반환해주세요.
- 규정 확인에 활용할만한 문장이 없다고 판단되면 [] 만 반환해주세요.

입력 예시:
25년 7월 25일에 제품설명회가 시행됬고 제품설명회로 구분돼 김도윤 PM이 참석하였고 장소는 코엑스 B홀에서 진행됬어 설명회에 언급된 제품은 텐텐이고 제품 리뉴얼 소개가 제품설명회 시행목적이였지 주요내용으로는 기존 제품의 문제점과 리뉴얼 되면서 바뀐점과 영양성분 소개야 참석한 직원들은 영업팀 손현성, 이용규, 손영식 이고 보건의료전문가는 서울대학병원 허한결 연세대학병원 최문영 교수가 참여했어 이후 저녁식사 자리를 가졌고 메뉴는 치킨이고 사용한 금액은 10만원이야 주류는 소주 2병, 맥주 6병을 마셨고 인당금액은 2만원이 나왔어

출력 예시(json형태):
[
  "25년 7월 25일에 제품설명회가 시행됐고 제품설명회로 구분돼 김도윤 PM이 참석하였고 장소는 코엑스 B홀에서 진행됐어",
  "설명회에 언급된 제품은 텐텐이고 제품 리뉴얼 소개가 제품설명회 시행 목적이었지 주요내용으로는 기존 제품의 문제점과 리뉴얼되면서 바뀐 점, 영양성분 소개야",
  "참석한 직원들은 영업팀 손현성, 이용규, 손영식이고 보건의료전문가는 서울대학병원 허한결, 연세대학병원 최문영 교수가 참여했어",
  "이후 저녁식사 자리를 가졌고 메뉴는 치킨이며 사용한 금액은 10만원이야 주류는 소주 2병, 맥주 6병을 마셨고 인당 금액은 2만원이 나왔어"
]
             출력 예시:


            """),
            ("human", "{content}")
        ])
        
        response = llm.invoke(extraction_prompt.format_messages(content=content))
        extracted_text = response.content.strip()
        
        print(f"📋 LLM 문구 추출 결과: {extracted_text}")
        
        # JSON 파싱
        try:
            if extracted_text.startswith('[') and extracted_text.endswith(']'):
                policy_phrases = json.loads(extracted_text)
            else:
                # JSON 형태가 아닌 경우 빈 리스트로 처리
                policy_phrases = []
        except json.JSONDecodeError:
            print("⚠️ JSON 파싱 실패, 빈 리스트로 처리")
            policy_phrases = []
        
        if not policy_phrases:
            print("✅ 규정 확인이 필요한 문구가 발견되지 않았습니다.")
            return "OK"
        
        print(f"🔍 추출된 규정 확인 대상 문구: {policy_phrases}")
        
        # 2단계: FastAPI를 통해 각 문구별로 유사한 규정 정보 검색
        violations = []
        fastapi_url = "http://localhost:8010/qa/question"
        
        for phrase in policy_phrases:
            try:
                # FastAPI 호출 - 올바른 페이로드 형식 사용
                payload = {
                    "question": phrase,
                    "top_k": 5,
                    "include_summary": True,
                    "include_sources": True
                }
                
                response = requests.post(
                    fastapi_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=30
                )
                
                if response.status_code == 200:
                    api_result = response.json()
                    if api_result.get('success', False):
                        search_results = api_result.get('search_results', [])
                        print(f"📊 '{phrase}' 검색 결과: {len(search_results)}개")
                        
                        # 3단계: LLM을 사용해 추출된 규정 정보와 비교하여 위반 여부 판단
                        violation_result = _check_phrase_against_regulations(phrase, search_results, llm)
                        if violation_result != "OK":
                            violations.append(f"{phrase}: {violation_result}")
                    else:
                        print(f"⚠️ API 응답 실패 ({phrase}): {api_result}")
                        violations.append(f"{phrase}: API 응답 오류")
                        
                else:
                    print(f"⚠️ FastAPI 호출 실패 ({phrase}): {response.status_code}")
                    violations.append(f"{phrase}: 규정 검색 실패 (HTTP {response.status_code})")
                    
            except requests.exceptions.RequestException as e:
                print(f"⚠️ API 호출 오류 ({phrase}): {e}")
                violations.append(f"{phrase}: 네트워크 오류로 규정 확인 불가")
            except Exception as e:
                print(f"⚠️ 처리 중 오류 ({phrase}): {e}")
                violations.append(f"{phrase}: 처리 오류 - {str(e)}")
        
        # 최종 결과 반환
        actual_violations = []
        for violation in violations:
            # "OK"가 포함되지 않은 실제 위반 사항만 추가
            if ": OK" not in violation and violation.strip() != "OK":
                actual_violations.append(violation)
        
        if actual_violations:
            return " | ".join(actual_violations)
        else:
            return "OK"
            
    except Exception as e:
        print(f"❌ 규정 검사 중 오류 발생: {e}")
        return f"규정 검사 오류: {str(e)}"

def _check_phrase_against_regulations(phrase: str, search_results: list, llm: ChatOpenAI) -> str:
    """추출된 문구를 규정 정보와 비교하여 위반 여부를 판단합니다."""
    
    try:
        if not search_results:
            return "관련 규정 정보를 찾을 수 없습니다"
        
        # 상위 3개 결과만 사용 (너무 많은 정보 방지)
        top_results = search_results[:3]
        regulations_text = "\n\n".join([
            f"규정 {i+1} (점수: {result.get('score', 0):.2f}):\n{result.get('source', {}).get('content', '')}" 
            for i, result in enumerate(top_results)
        ])

        # 기존 프롬프트(위반 사항 남발함)
        # 다음 문구가 제공된 회사 규정을 위반하는지 분석해주세요.

        # 분석 기준:
        # 1. 명확한 규정 위반이 있는지 확인
        # 2. 잠재적 위험이나 주의가 필요한 사항이 있는지 확인
        # 3. 규정에 명시되지 않았더라도 일반적인 컴플라이언스 관점에서 문제가 될 수 있는지 확인

        # 응답 형식:
        # - 위반이나 문제가 없으면: "OK"
        # - 문제가 있으면: 구체적인 위반 내용을 간단히 설명
        validation_prompt = ChatPromptTemplate.from_messages([
            ("system", """
다음 문구가 제공된 회사 규정을 위반하는지 분석해주세요.

분석 기준:
1. 명확하게 규정 위반이 있는지 확인
2. 위반 문제가 있어보이는 것이 아닌 명확하게 규정을 위반한것만 문제로 판단

응답 형식:
- 위반이나 문제가 없으면: "OK"
- 문제가 있으면: 구체적인 위반 내용을 간단히 설명
            """),
            ("human", "확인할 문구: {phrase}\n\n관련 규정 정보:\n{regulations}")
        ])
        
        response = llm.invoke(validation_prompt.format_messages(
            phrase=phrase, 
            regulations=regulations_text
        ))
        
        result = response.content.strip()
        print(f"🔍 '{phrase}' 규정 검사 결과: {result[:100]}{'...' if len(result) > 100 else ''}")
        
        return result
        
    except Exception as e:
        print(f"⚠️ 규정 비교 중 오류: {e}")
        return f"규정 비교 오류: {str(e)}"

@tool
def convert_structured_to_natural_text(structured_data: Annotated[str, "JSON 형태의 구조화된 데이터"]) -> str:
    """구조화된 데이터를 자연스러운 원문 형태로 변환합니다."""
    
    try:
        # JSON 파싱
        try:
            if isinstance(structured_data, str):
                import json
                data = json.loads(structured_data) if structured_data.startswith('{') else eval(structured_data)
            else:
                data = structured_data
        except (json.JSONDecodeError, SyntaxError) as e:
            return f"데이터 파싱 오류: {str(e)}"
        
        # LLM을 사용해 자연스러운 문장으로 변환
        llm = ChatOpenAI(model="gpt-4o", temperature=0.3)
        
        conversion_prompt = ChatPromptTemplate.from_messages([
            ("system", """
주어진 구조화된 데이터를 자연스러운 한국어 문장으로 변환해주세요.

변환 규칙:
1. 모든 정보를 빠짐없이 포함해야 합니다
2. 자연스럽고 읽기 쉬운 문장으로 작성해주세요
3. 구어체 형태로 변환해주세요 (예: ~이야, ~야, ~음, ~지)
4. 논리적인 순서로 정보를 배치해주세요
5. 날짜, 연락처, 사이트 등의 정확한 정보는 그대로 유지해주세요

예시 변환:
입력: {{"방문제목": "ABC병원 방문", "방문날짜": "240101", "Client": "ABC병원"}}
출력: 방문 제목은 ABC병원 방문이고 방문일은 240101이고 client는 ABC병원이야

한 문단으로 자연스럽게 연결된 문장을 작성해주세요.
            """),
            ("human", "다음 구조화된 데이터를 자연스러운 원문으로 변환해주세요:\n\n{data}")
        ])
        
        # 데이터를 문자열 형태로 변환
        data_str = str(data) if not isinstance(data, str) else data
        
        response = llm.invoke(conversion_prompt.format_messages(data=data_str))
        natural_text = response.content.strip()
        
        print(f"📝 구조화된 데이터 → 자연어 변환 완료")
        print(f"🔍 변환된 텍스트 길이: {len(natural_text)}자")
        
        return natural_text
        
    except Exception as e:
        print(f"❌ 데이터 변환 중 오류 발생: {e}")
        return f"데이터 변환 오류: {str(e)}"

@tool
def separate_document_type_and_content(user_input: Annotated[str, "사용자가 입력한 텍스트"]) -> str:
    """사용자 입력에서 문서 양식 분류와 관련된 내용과 문서 양식에 들어갈 내용을 분리합니다."""
    
    try:
        llm = ChatOpenAI(model="gpt-4o", temperature=0.1)
        
        separation_prompt = ChatPromptTemplate.from_messages([
            ("system", """
사용자가 입력한 텍스트를 분석하여 문서 양식 분류와 관련된 내용과 실제 문서에 들어갈 내용을 분리해주세요.

분리 기준:
1. 문서 양식 분류: "~을/를 작성할거야", "~서류를 만들어줘", "~계획서 작성", "~보고서 준비" 등 문서의 종류나 형태를 명시하는 부분
2. 문서 내용: 실제 문서에 포함될 구체적인 정보, 데이터, 내용

응답 형식은 JSON으로 반환해주세요:
{{
    "document_type": "문서 양식 분류 관련 내용",
    "content": "문서에 들어갈 실제 내용"
}}

예시:
입력: "제품설명회 계획서를 작성할거야. 25년 7월 25일에 제품설명회가 시행되며..."
출력: {{
    "document_type": "제품설명회 계획서를 작성할거야",
    "content": "25년 7월 25일에 제품설명회가 시행되며..."
}}

만약 문서 양식 분류 부분이 명확하지 않다면 document_type을 빈 문자열로, 
문서 내용이 없다면 content를 빈 문자열로 설정해주세요.
            """),
            ("human", "{user_input}")
        ])
        
        response = llm.invoke(separation_prompt.format_messages(user_input=user_input))
        result = response.content.strip()
        
        print(f"📋 문서 분류 및 내용 분리 결과: {result}")
        
        # JSON 코드 블록 제거 (```json ... ``` 형태)
        if result.startswith('```json'):
            result = result.replace('```json', '').replace('```', '').strip()
        elif result.startswith('```'):
            result = result.replace('```', '').strip()
        
        # JSON 파싱 검증
        try:
            parsed = json.loads(result)
            if 'document_type' in parsed and 'content' in parsed:
                return result
            else:
                print("⚠️ 필수 키가 누락된 응답")
                return json.dumps({
                    "document_type": "",
                    "content": user_input
                }, ensure_ascii=False)
        except json.JSONDecodeError:
            print("⚠️ JSON 파싱 실패")
            return json.dumps({
                "document_type": "",
                "content": user_input
            }, ensure_ascii=False)
        
    except Exception as e:
        print(f"❌ 문서 분류 및 내용 분리 중 오류 발생: {e}")
        return json.dumps({
            "document_type": "",
            "content": user_input
        }, ensure_ascii=False)