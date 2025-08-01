import React, { useState, useEffect, useRef } from 'react';
import './ChatScreen.css';

const ChatScreen = () => {
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState('router');
  const [chatHistory, setChatHistory] = useState([]);
  const [currentChatId, setCurrentChatId] = useState(null);
  const [sessionId, setSessionId] = useState(null);
  const [currentSessionAgent, setCurrentSessionAgent] = useState(null); // 현재 세션의 고정 에이전트
  const [isWaitingForDocsInput, setIsWaitingForDocsInput] = useState(false); // Docs Agent 입력 대기 상태
  const [docsInputType, setDocsInputType] = useState(null); // Docs Agent 입력 타입
  const messagesEndRef = useRef(null);

  // session_id 생성 함수 - 각 채팅방마다 고유 ID
  const generateSessionId = () => {
    // 새로운 세션 ID 생성 (각 채팅방마다 고유)
    const newSessionId = `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    console.log('새 세션 ID 생성:', newSessionId);
    return newSessionId;
  };

  // 백엔드 에이전트 ID를 프론트엔드 키로 매핑
  const agentKeyMapping = {
    'employee_agent': 'employee',
    'client_agent': 'client',
    'search_agent': 'search',
    'create_document_agent': 'docs'
  };

  // 에이전트 표시 이름
  const AGENT_DISPLAY_NAMES = {
    'employee_agent': '직원 실적 분석',
    'client_agent': '고객/거래처 분석',
    'search_agent': '정보 검색',
    'create_document_agent': '문서 생성',
    'docs_agent': '문서 생성'
  };

  // 4개 에이전트 정보
  const agents = {
    router: {
      name: 'Router Agent',
      endpoint: '/api/chat',  // 원래 API 경로
      description: '쿼리를 분석하고 적절한 에이전트로 자동 라우팅',
      color: '#3b82f6'
    },
    employee: {
      name: 'Employee Agent',
      endpoint: '/api/select-agent',  // 백엔드 실제 경로로 수정
      description: '직원 실적 분석 및 평가',
      color: '#10b981',
      agentType: 'employee_agent'
    },
    client: {
      name: 'Client Agent',
      endpoint: '/api/select-agent',  // 백엔드 실제 경로로 수정
      description: '고객/거래처 분석 및 영업 전략',
      color: '#f59e0b',
      agentType: 'client_agent'
    },
    search: {
      name: 'Search Agent',
      endpoint: '/api/select-agent',
      description: '정보 검색',
      color: '#06b6d4',
      agentType: 'search_agent'
    },
    docs: {
      name: 'Docs Agent',
      endpoint: '/api/select-agent',  // 백엔드 실제 경로로 수정
      description: '문서 분류 및 생성',
      color: '#8b5cf6',
      agentType: 'create_document_agent'
    }
  };

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // 백엔드에서 채팅 내역 불러오기
  const loadChatHistoryFromBackend = async () => {
    try {
      console.log('🔄 백엔드에서 모든 세션 불러오는 중...');
      const response = await fetch('http://localhost:8000/api/all-sessions');
      
      if (response.ok) {
        const data = await response.json();
        if (data.success && data.sessions) {
          console.log(`✅ 백엔드에서 ${data.count}개 세션 불러옴`);
          
          // 세션 데이터를 채팅 히스토리 형식으로 변환
          const chatHistoryFromDB = data.sessions.map(session => ({
            id: session.id,
            sessionId: session.sessionId,
            title: session.title,
            messages: [], // 메시지는 선택할 때 로드
            createdAt: session.createdAt,
            messageCount: session.messageCount
          }));
          
          // localStorage의 기존 데이터와 병합 (중복 제거)
          const savedHistory = localStorage.getItem('chatHistory');
          let localHistory = [];
          if (savedHistory) {
            localHistory = JSON.parse(savedHistory);
          }
          
          // sessionId를 기준으로 중복 제거
          const mergedHistory = [...chatHistoryFromDB];
          localHistory.forEach(localChat => {
            if (!mergedHistory.find(dbChat => dbChat.sessionId === localChat.sessionId)) {
              mergedHistory.push(localChat);
            }
          });
          
          setChatHistory(mergedHistory);
          localStorage.setItem('chatHistory', JSON.stringify(mergedHistory));
          
          return mergedHistory;
        }
      }
      
      console.log('⚠️ 백엔드에서 세션 목록 없음, localStorage 사용');
      // 백엔드에 데이터가 없으면 localStorage 사용
      const savedHistory = localStorage.getItem('chatHistory');
      if (savedHistory) {
        const localHistory = JSON.parse(savedHistory);
        setChatHistory(localHistory);
        return localHistory;
      }
      
      return [];
    } catch (error) {
      console.error('❌ 세션 목록 불러오기 실패:', error);
      
      // 오류 시 localStorage 폴백
      const savedHistory = localStorage.getItem('chatHistory');
      if (savedHistory) {
        const localHistory = JSON.parse(savedHistory);
        setChatHistory(localHistory);
        return localHistory;
      }
      
      return [];
    }
  };

  // 초기 안내 메시지
  useEffect(() => {
    const initializeChat = async () => {
      // 시스템 안내 메시지
      const systemMessage = {
        type: 'system',
        content: '안녕하세요! NaruTalk AI Assistant입니다. 무엇을 도와드릴까요?',
        timestamp: new Date().toLocaleTimeString()
      };
      
      // 에이전트 선택 메시지 (H2H와 동일한 형태)
      const agentSelectionMessage = {
        type: 'agent_selection',
        content: `저희 시스템은 다음 기능을 제공합니다:
- 직원 실적/평가 조회
- 고객/거래처(병원,약국) 정보 관리
- 영업 데이터 검색
- 보고서/문서 자동 생성

원하시는 기능을 선택하시거나, 바로 질문을 입력하셔도 됩니다.`,
        timestamp: new Date().toLocaleTimeString(),
        agent: 'System',
        query: '',  // 초기 선택이므로 query 없음
        available_agents: ['employee_agent', 'client_agent', 'search_agent', 'create_document_agent'],
        agent_descriptions: {
          "employee_agent": "사내 직원에 대한 정보 제공을 담당합니다. 예: 개인 실적 조회, 인사 이력, 직책, 소속 부서, 조직도 확인, 성과 평가 등 직원 관련 질의 응답을 처리합니다.",
          "client_agent": "고객 및 거래처에 대한 정보를 제공합니다. 반드시 병원, 제약영업과 관련이 있는 질문에만 답변합니다.예: 특정 고객의 매출 추이, 거래 이력, 등급 분류, 잠재 고객 분석, 영업 성과 분석 등 외부 고객 관련 질문에 대응합니다.",
          "search_agent": "내부 데이터베이스에서 정보 검색을 수행합니다. 예: 문서 검색, 사내 규정, 업무 매뉴얼, 제품 정보, 교육 자료 등 특정 정보를 정제된 DB 또는 벡터DB 기반으로 검색합니다.",
          "create_document_agent": "문서 자동 생성 및 규정 검토를 담당합니다. 예: 보고서 초안 자동 생성, 전표/계획서 생성, 컴플라이언스 위반 여부 판단, 서식 분석 및 문서 오류 검토 등의 기능을 수행합니다."
        },
        agent_display_names: {
          "employee_agent": "직원 실적 분석",
          "client_agent": "고객/거래처 분석",
          "search_agent": "정보 검색",
          "create_document_agent": "문서 생성"
        }
      };
      
      // 백엔드에서 모든 세션 목록 불러오기
      const history = await loadChatHistoryFromBackend();
      
      // 세션이 있으면 첫 번째 세션 선택, 없으면 새 채팅 시작
      if (history.length > 0) {
        console.log(`📚 ${history.length}개의 세션 발견`);
        // 가장 최근 세션 선택
        const mostRecentSession = history[0];
        if (mostRecentSession.sessionId) {
          await selectChat(mostRecentSession.id);
        } else {
          // 기본 메시지 표시하고 새 채팅 시작
          setMessages([systemMessage, agentSelectionMessage]);
          startNewChat();
        }
      } else {
        console.log('📝 세션이 없음, 새 채팅 시작');
        // 기본 메시지 표시
        setMessages([systemMessage, agentSelectionMessage]);
        startNewChat();
      }
    };
    
    initializeChat();
  }, []);

  // 새로운 채팅 시작
  const startNewChat = () => {
    const chatId = Date.now().toString();
    const newSessionId = generateSessionId();
    
    // 시스템 메시지
    const systemMessage = {
      type: 'system',
      content: '안녕하세요! NaruTalk AI Assistant입니다. 무엇을 도와드릴까요?',
      timestamp: new Date().toLocaleTimeString()
    };
    
    // 에이전트 선택 메시지
    const agentSelectionMessage = {
      type: 'agent_selection',
      content: `저희 시스템은 다음 기능을 제공합니다:
- 직원 실적/평가 조회
- 고객/거래처(병원,약국) 정보 관리
- 영업 데이터 검색
- 보고서/문서 자동 생성

원하시는 기능을 선택하시거나, 바로 질문을 입력하셔도 됩니다.`,
      timestamp: new Date().toLocaleTimeString(),
      agent: 'System',
      query: '',
      available_agents: ['employee_agent', 'client_agent', 'search_agent', 'create_document_agent'],
      agent_descriptions: {
        "employee_agent": "사내 직원에 대한 정보 제공을 담당합니다. 예: 개인 실적 조회, 인사 이력, 직책, 소속 부서, 조직도 확인, 성과 평가 등 직원 관련 질의 응답을 처리합니다.",
        "client_agent": "고객 및 거래처에 대한 정보를 제공합니다. 반드시 병원, 제약영업과 관련이 있는 질문에만 답변합니다.예: 특정 고객의 매출 추이, 거래 이력, 등급 분류, 잠재 고객 분석, 영업 성과 분석 등 외부 고객 관련 질문에 대응합니다.",
        "search_agent": "내부 데이터베이스에서 정보 검색을 수행합니다. 예: 문서 검색, 사내 규정, 업무 매뉴얼, 제품 정보, 교육 자료 등 특정 정보를 정제된 DB 또는 벡터DB 기반으로 검색합니다.",
        "create_document_agent": "문서 자동 생성 및 규정 검토를 담당합니다. 예: 보고서 초안 자동 생성, 전표/계획서 생성, 컴플라이언스 위반 여부 판단, 서식 분석 및 문서 오류 검토 등의 기능을 수행합니다."
      },
      agent_display_names: {
        "employee_agent": "직원 실적 분석",
        "client_agent": "고객/거래처 분석",
        "search_agent": "정보 검색",
        "create_document_agent": "문서 생성"
      }
    };
    
    setMessages([systemMessage, agentSelectionMessage]);
    setCurrentChatId(chatId);
    setSessionId(newSessionId);
    
    // 새 채팅을 히스토리에 추가
    const newChat = {
      id: chatId,
      sessionId: newSessionId,
      title: `채팅 ${new Date().toLocaleString()}`,
      messages: [systemMessage, agentSelectionMessage],
      createdAt: new Date().toISOString()
    };
    
    const updatedHistory = [newChat, ...chatHistory];
    setChatHistory(updatedHistory);
    localStorage.setItem('chatHistory', JSON.stringify(updatedHistory));
  };

  // 채팅 내역 선택
  const selectChat = async (chatId) => {
    const selectedChat = chatHistory.find(chat => chat.id === chatId);
    if (selectedChat) {
      setCurrentChatId(chatId);
      setSessionId(selectedChat.sessionId);
      
      // 메시지가 이미 로드되어 있으면 바로 사용
      if (selectedChat.messages && selectedChat.messages.length > 0) {
        setMessages(selectedChat.messages);
      } else {
        // 백엔드에서 메시지 불러오기 - DB에서 직접 조회
        try {
          // sessionId가 있는지 확인
          if (!selectedChat.sessionId) {
            console.error('세션 ID가 없습니다:', selectedChat);
            setMessages(selectedChat.messages || []);
            return;
          }
          
          console.log(`🔄 세션 ${selectedChat.sessionId}의 메시지 불러오는 중...`);
          const response = await fetch(`http://localhost:8000/api/chat-history/${selectedChat.sessionId}`);
          
          if (response.ok) {
            const data = await response.json();
            if (data.success && data.messages && data.messages.length > 0) {
              console.log(`✅ ${data.count}개 메시지 불러옴`);
              
              // DB에서 가져온 메시지 형식을 프론트엔드 형식으로 변환
              const formattedMessages = data.messages.map(msg => ({
                type: msg.role === 'user' ? 'user' : msg.role === 'assistant' ? 'bot' : 'system',
                content: msg.content,
                timestamp: msg.timestamp ? new Date(msg.timestamp).toLocaleTimeString() : new Date().toLocaleTimeString(),
                agent: msg.metadata?.agent || 'System'
              }));
              
              setMessages(formattedMessages);
              
              // 채팅 히스토리 업데이트
              const updatedHistory = chatHistory.map(chat => 
                chat.id === chatId 
                  ? { ...chat, messages: formattedMessages }
                  : chat
              );
              setChatHistory(updatedHistory);
              localStorage.setItem('chatHistory', JSON.stringify(updatedHistory));
            } else {
              console.log('해당 세션에 메시지가 없습니다.');
              setMessages(selectedChat.messages || []);
            }
          } else {
            console.error('메시지 불러오기 실패:', response.status);
            setMessages(selectedChat.messages || []);
          }
        } catch (error) {
          console.error('메시지 불러오기 오류:', error);
          setMessages(selectedChat.messages || []);
        }
      }
    }
  };

  // 채팅 내역 초기화
  const clearAllChats = () => {
    if (window.confirm('모든 채팅 내역을 삭제하시겠습니까?')) {
      setChatHistory([]);
      localStorage.removeItem('chatHistory');
      startNewChat();
    }
  };

  // 메시지 저장 (채팅 내역 업데이트)
  const saveMessageToHistory = (newMessages) => {
    if (currentChatId) {
      const updatedHistory = chatHistory.map(chat => {
        if (chat.id === currentChatId) {
          return {
            ...chat,
            messages: newMessages,
            sessionId: sessionId || chat.sessionId, // sessionId 유지
            title: newMessages.length > 1 ? 
              newMessages[1].content.substring(0, 30) + '...' : 
              chat.title
          };
        }
        return chat;
      });
      setChatHistory(updatedHistory);
      localStorage.setItem('chatHistory', JSON.stringify(updatedHistory));
    }
  };

  const sendMessage = async () => {
    if (!inputValue.trim() || isLoading) return;

    const userMessage = {
      type: 'user',
      content: inputValue,
      timestamp: new Date().toLocaleTimeString()
    };

    const newMessages = [...messages, userMessage];
    setMessages(newMessages);
    setIsLoading(true);
    const currentQuery = inputValue;
    setInputValue('');
    
    // Docs Agent 입력 대기 상태 초기화
    setIsWaitingForDocsInput(false);
    setDocsInputType(null);

    try {
      // 항상 Router를 통해 전송하여 동적 라우팅 활성화
      const requestBody = { 
        session_id: sessionId,
        query: currentQuery 
      };

      const response = await fetch('http://localhost:8000/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestBody)
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      
      // 디버깅용 로그
      console.log('API 응답 데이터:', data);
      if (data.type === 'multi') {
        console.log('멀티 태스크 응답 구조:');
        console.log('- response:', data.response);
        console.log('- tasks:', data.tasks);
        console.log('- detailed_results:', data.detailed_results);
        if (data.response && data.response.steps) {
          console.log('- response.steps:', data.response.steps);
        }
      }
      
      let botResponseContent = '';
      let responseAgent = 'Router Agent';
      
      if (data.success) {
        // Router 에이전트에서 사용자 선택이 필요한 경우
        if (data.needs_user_selection) {
          const selectionMessage = {
            type: 'agent_selection',
            content: data.message,
            timestamp: new Date().toLocaleTimeString(),
            agent: 'Router Agent',
            query: currentQuery,
            available_agents: data.available_agents,
            agent_descriptions: data.agent_descriptions,
            agent_display_names: data.agent_display_names
          };
          
          const messagesWithSelection = [...newMessages, selectionMessage];
          setMessages(messagesWithSelection);
          saveMessageToHistory(messagesWithSelection);
          return;
        }
        
        // Docs Agent의 대화형 응답 처리
        if (data.agent === 'docs_agent' && data.waiting_for_input) {
          const interactiveMessage = {
            type: 'interactive',
            content: data.response,
            timestamp: new Date().toLocaleTimeString(),
            agent: 'Docs Agent',
            waiting_for_input: true,
            input_type: data.input_type,
            options: data.options || null,
            step: data.step
          };
          
          const messagesWithInteractive = [...newMessages, interactiveMessage];
          setMessages(messagesWithInteractive);
          saveMessageToHistory(messagesWithInteractive);
          
          // 입력 대기 상태로 설정
          setIsWaitingForDocsInput(true);
          setDocsInputType(data.input_type);
          setIsLoading(false);
          return;
        }
        
        // 응답에서 실제 사용된 에이전트 정보 추출
        const usedAgent = data.agent || data.classification_result?.split(': ')[1];
        if (usedAgent) {
          responseAgent = AGENT_DISPLAY_NAMES[usedAgent] || usedAgent;
        }
        
        // 기본 응답 내용
        // 단일 태스크 응답 처리 (type이 'single'인 경우)
        if (data.type === 'single') {
          console.log('단일 태스크 응답 처리');
          // response가 객체인 경우
          if (typeof data.response === 'object' && data.response !== null) {
            if (data.response.success === false) {
              botResponseContent = `❌ 오류: ${data.response.error || data.response.response || '알 수 없는 오류'}`;
            } else if (data.response.response) {
              botResponseContent = data.response.response;
            } else if (data.response.message) {
              botResponseContent = data.response.message;
            } else {
              botResponseContent = JSON.stringify(data.response, null, 2);
            }
          } else {
            botResponseContent = data.response || '응답을 처리할 수 없습니다.';
          }
        }
        // 멀티 태스크 응답 처리 (type이 'multi'인 경우)
        else if (data.type === 'multi') {
          console.log('멀티 태스크 응답 처리 시작');
          botResponseContent = '';
          
          // response.steps가 있는 경우 (구조화된 응답)
          if (data.response && data.response.steps && Array.isArray(data.response.steps)) {
            console.log('steps 발견:', data.response.steps);
            
            // summary는 맨 위에 표시
            if (data.response.summary) {
              botResponseContent = data.response.summary + '\n\n';
            }
            
            // 각 step의 세부 결과 표시
            botResponseContent += '## 상세 결과:\n\n';
            
            data.response.steps.forEach((step) => {
              botResponseContent += `### ${step.step}. ${step.description}\n`;
              botResponseContent += `**에이전트**: ${AGENT_DISPLAY_NAMES[step.agent] || step.agent}\n`;
              botResponseContent += `**상태**: ${step.status === 'completed' ? '✅ 완료' : '⏳ 진행중'}\n\n`;
              
              // 결과 내용 표시
              if (step.result) {
                botResponseContent += `**결과**:\n`;
                // result가 객체인 경우
                if (typeof step.result === 'object') {
                  if (step.result.success === false) {
                    botResponseContent += `❌ 오류: ${step.result.error || step.result.response || '알 수 없는 오류'}\n`;
                  } else if (step.result.response) {
                    botResponseContent += `${step.result.response}\n`;
                  } else if (step.result.message) {
                    botResponseContent += `${step.result.message}\n`;
                  } else {
                    botResponseContent += `${JSON.stringify(step.result, null, 2)}\n`;
                  }
                } else {
                  botResponseContent += `${step.result}\n`;
                }
              }
              
              botResponseContent += '\n---\n\n';
            });
          }
          // detailed_results가 있는 경우 (백업)
          else if (data.detailed_results) {
            // 태스크 정보를 사용하여 순서대로 표시
            if (data.tasks && Array.isArray(data.tasks)) {
              data.tasks.forEach((task) => {
                const result = data.detailed_results[task.id];
                if (result) {
                  botResponseContent += `### ${task.id + 1}. ${task.description}\n`;
                  botResponseContent += `**에이전트**: ${AGENT_DISPLAY_NAMES[task.agent] || task.agent}\n`;
                  botResponseContent += `**상태**: ✅ 완료\n`;
                  
                  // 결과 내용 표시
                  if (typeof result === 'object') {
                    if (result.response) {
                      botResponseContent += `**결과**:\n${result.response}\n`;
                    } else if (result.message) {
                      botResponseContent += `**결과**:\n${result.message}\n`;
                    } else {
                      botResponseContent += `**결과**:\n${JSON.stringify(result, null, 2)}\n`;
                    }
                  } else {
                    botResponseContent += `**결과**:\n${result}\n`;
                  }
                  
                  botResponseContent += '\n---\n\n';
                }
              });
            }
          }
          // 둘 다 없으면 summary만 표시
          else if (data.response && data.response.summary) {
            botResponseContent = data.response.summary;
          }
          
          // pending_docs_tasks가 있으면 추가 안내
          if (data.pending_docs_tasks && data.pending_docs_tasks.length > 0) {
            botResponseContent += '\n\n📝 **문서 생성 작업 안내**:\n';
            botResponseContent += '문서 생성은 대화형 작업이므로 별도로 진행해주세요:\n';
            data.pending_docs_tasks.forEach((task) => {
              botResponseContent += `- ${task.description}\n`;
            });
          }
        }
        // response가 객체인 경우 (기존 멀티 태스크 응답)
        else if (typeof data.response === 'object' && data.response !== null) {
          // summary가 있으면 먼저 표시
          if (data.response.summary) {
            botResponseContent = data.response.summary + '\n\n';
          } else {
            botResponseContent = '';
          }
          
          // 각 태스크별 결과 표시
          if (data.response.tasks && Array.isArray(data.response.tasks)) {
            data.response.tasks.forEach((task, index) => {
              botResponseContent += `### ${index + 1}. ${task.description}\n`;
              botResponseContent += `**상태**: ${task.status === 'completed' ? '✅ 완료' : '⏳ 진행중'}\n`;
              
              // 각 태스크의 결과 표시
              if (task.result) {
                if (typeof task.result === 'string') {
                  botResponseContent += `**결과**: ${task.result}\n`;
                } else if (task.result.response) {
                  botResponseContent += `**결과**: ${task.result.response}\n`;
                } else {
                  botResponseContent += `**결과**: ${JSON.stringify(task.result, null, 2)}\n`;
                }
              }
              
              botResponseContent += '\n';
            });
          }
          
          // tasks가 없으면 전체 응답을 JSON으로 표시
          if (!data.response.tasks && !data.response.summary) {
            botResponseContent = JSON.stringify(data.response, null, 2);
          }
        } else {
          botResponseContent = data.response || data.message || '처리가 완료되었습니다.';
        }
        
        // 라우팅 정보가 있으면 추가
        if (data.classification_result) {
          botResponseContent += `\n\n[${data.classification_result}]`;
        }
        
        // Docs Agent 완료 메시지 처리
        if (data.agent === 'docs_agent' && data.step === 'completed') {
          if (data.document) {
            botResponseContent += '\n\n📄 생성된 문서:\n' + data.document;
          }
          if (data.file_path) {
            botResponseContent += `\n\n💾 파일 위치: ${data.file_path}`;
          }
        }
      } else {
        botResponseContent = `❌ 오류 발생: ${data.error || data.message}`;
      }

      const botMessage = {
        type: 'bot',
        content: botResponseContent,
        timestamp: new Date().toLocaleTimeString(),
        agent: responseAgent
      };

      const finalMessages = [...newMessages, botMessage];
      setMessages(finalMessages);
      saveMessageToHistory(finalMessages);

      // 에이전트가 새로 선택되었거나 변경된 경우 현재 에이전트 정보 갱신
      if (data.agent_selected || data.agent_fixed) {
        checkCurrentAgent(sessionId);
      }

      // 남은 작업이 있으면 사용자에게 안내
      if (data.remaining_tasks && data.remaining_tasks.length > 0) {
        console.log(`남은 작업 ${data.remaining_tasks.length}개`);
        
        // 남은 작업 안내 메시지
        setTimeout(() => {
          const remainingMessage = {
            type: 'system',
            content: `📋 총 ${data.total_tasks}개 작업 중 ${data.current_task_index}번째 완료\n\n남은 작업들:\n${data.remaining_tasks.map((task, idx) => `${idx + 1}. ${task.description}`).join('\n')}\n\n계속하려면 다음 질문을 입력해주세요.`,
            timestamp: new Date().toLocaleTimeString()
          };
          
          const messagesWithRemaining = [...finalMessages, remainingMessage];
          setMessages(messagesWithRemaining);
          saveMessageToHistory(messagesWithRemaining);
        }, 500);
      }

    } catch (error) {
      console.error('API 요청 오류:', error);
      const errorMessage = {
        type: 'bot',
        content: `❌ 연결 오류: ${error.message}\n\n백엔드 서버가 실행 중인지 확인해주세요. (http://localhost:8000)`,
        timestamp: new Date().toLocaleTimeString(),
        agent: 'System'
      };
      const finalMessages = [...newMessages, errorMessage];
      setMessages(finalMessages);
      saveMessageToHistory(finalMessages);
    } finally {
      setIsLoading(false);
    }
  };

  // 에이전트 선택 처리 함수
  const handleAgentSelection = async (query, selectedAgentKey) => {
    setIsLoading(true);

    try {
      // 초기 화면에서 선택하는 경우 (query가 비어있음)
      const endpoint = query === '' ? '/api/initial-agent-select' : '/api/select-agent';
      
      const response = await fetch(`http://localhost:8000${endpoint}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          session_id: sessionId,
          query: query,
          selected_agent: selectedAgentKey
        })
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      
      if (data.success) {
        if (data.needs_new_question) {
          // 예시 질문을 보여주는 특별한 메시지 타입
          const guideMessage = {
            type: 'agent_guide',
            content: data.message,
            timestamp: new Date().toLocaleTimeString(),
            agent: 'System',
            selected_agent: data.selected_agent,
            example_questions: data.example_questions
          };
          
          const updatedMessages = [...messages, guideMessage];
          setMessages(updatedMessages);
          saveMessageToHistory(updatedMessages);
          
          // 선택된 에이전트는 표시용으로만 사용하고 고정하지 않음
          // 모든 메시지는 Router를 통해 동적으로 라우팅됨
        } else {
          // 실제 에이전트 응답
          const botMessage = {
            type: 'bot',
            content: data.response || data.message,
            timestamp: new Date().toLocaleTimeString(),
            agent: data.agent
          };
          
          const updatedMessages = [...messages, botMessage];
          setMessages(updatedMessages);
          saveMessageToHistory(updatedMessages);
          
          checkCurrentAgent(sessionId);
        }
      } else {
        const errorMessage = {
          type: 'bot',
          content: `❌ 에이전트 선택 처리 오류: ${data.error || data.message}`,
          timestamp: new Date().toLocaleTimeString(),
          agent: 'System'
        };
        
        const updatedMessages = [...messages, errorMessage];
        setMessages(updatedMessages);
        saveMessageToHistory(updatedMessages);
      }

    } catch (error) {
      console.error('에이전트 선택 처리 오류:', error);
      const errorMessage = {
        type: 'bot',
        content: `❌ 에이전트 선택 처리 중 오류 발생: ${error.message}`,
        timestamp: new Date().toLocaleTimeString(),
        agent: 'System'
      };
      const updatedMessages = [...messages, errorMessage];
      setMessages(updatedMessages);
      saveMessageToHistory(updatedMessages);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  // 첫 번째 채팅이 없으면 자동으로 생성
  useEffect(() => {
    if (chatHistory.length === 0 && !currentChatId) {
      startNewChat();
    }
  }, []);

  // 현재 세션의 선택된 에이전트 확인
  const checkCurrentAgent = async (sessionId) => {
    if (!sessionId) return;
    
    try {
      const response = await fetch(`http://localhost:8000/api/current-agent/${sessionId}`);
      if (response.ok) {
        const data = await response.json();
        if (data.success && data.has_selected_agent) {
          setCurrentSessionAgent(data.agent_info);
          console.log(`✅ 현재 세션 에이전트: ${data.agent_info.agent_name}`);
        } else {
          setCurrentSessionAgent(null);
          console.log('📝 현재 세션에 고정된 에이전트 없음');
        }
      }
    } catch (error) {
      console.error('❌ 현재 에이전트 확인 실패:', error);
    }
  };

  useEffect(() => {
    checkCurrentAgent(sessionId);
  }, [sessionId]);

  // 에이전트 초기화
  const resetAgent = async () => {
    if (!sessionId) return;
    
    if (!window.confirm('현재 에이전트를 초기화하시겠습니까?\n다음 질문부터 새로운 에이전트가 선택됩니다.')) {
      return;
    }

    try {
      const response = await fetch('http://localhost:8000/api/reset-agent', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          session_id: sessionId
        })
      });

      if (response.ok) {
        const data = await response.json();
        if (data.success) {
          setCurrentSessionAgent(null);
          
          // 시스템 메시지 추가
          const resetMessage = {
            type: 'system',
            content: data.message,
            timestamp: new Date().toLocaleTimeString(),
            agent: 'System'
          };
          
          const updatedMessages = [...messages, resetMessage];
          setMessages(updatedMessages);
          saveMessageToHistory(updatedMessages);
          
          console.log('✅ 에이전트 초기화 완료');
        }
      }
    } catch (error) {
      console.error('❌ 에이전트 초기화 실패:', error);
    }
  };

  return (
    <div className="chat-screen">
      {/* Chat Management Panel */}
      <aside className="chat-panel">
          <div className="chat-management">
            <h3>Chat</h3>
            <button className="new-chat-btn" onClick={startNewChat}>
              + New Chat
            </button>
            
            <div className="chat-controls">
              <button 
                className="clear-chat-btn" 
                onClick={clearAllChats}
                title="모든 채팅 삭제"
              >
                🗑️ 전체 삭제
              </button>
            </div>
            
            <div className="chat-list">
              {chatHistory.map((chat) => (
                <div 
                  key={chat.id}
                  className={`chat-item ${currentChatId === chat.id ? 'active' : ''}`}
                  onClick={() => selectChat(chat.id)}
                >
                  <span className="chat-icon">💬</span>
                  <div className="chat-info">
                    <div className="chat-title-text">
                      {chat.title}
                      {chat.messageCount && (
                        <span style={{fontSize: '12px', color: '#999', marginLeft: '5px'}}>
                          ({chat.messageCount}개 메시지)
                        </span>
                      )}
                    </div>
                    <div className="chat-date">
                      {new Date(chat.createdAt).toLocaleDateString()}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </aside>

        {/* Main Content */}
        <div className="chat-container">
          {/* Main Chat Area */}
        <main className="chat-main">
          <div className="chat-title">
            <h2>AI 채팅</h2>
            
            {/* 현재 세션 에이전트 표시 */}
            {currentSessionAgent ? (
              <div className="current-agent-info">
                <div className="agent-badge">
                  🎯 <strong>{currentSessionAgent.agent_name}</strong> (고정됨)
                </div>
                <button 
                  className="reset-agent-btn"
                  onClick={resetAgent}
                  title="에이전트 초기화"
                >
                  🔄 초기화
                </button>
              </div>
            ) : (
              <div className="agent-selector">
                <label>에이전트 선택:</label>
                <select 
                  value={selectedAgent} 
                  onChange={(e) => setSelectedAgent(e.target.value)}
                  className="agent-select"
                >
                  {Object.entries(agents).map(([key, agent]) => (
                    <option key={key} value={key}>
                      {agent.name}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>

          <div className="messages-container">
            {messages.map((message, index) => (
              <div key={index} className={`message ${message.type === 'user' ? 'user-message' : 'ai-message'}`}>
                <div className="message-header">
                  <span className="message-sender">
                    {message.type === 'user' ? '👤 사용자' : 
                     message.type === 'system' ? '🤖 시스템' : 
                     `🤖 ${message.agent || 'AI'}`}
                  </span>
                  <span className="message-time">{message.timestamp}</span>
                </div>
                <div className="message-content">
                  {message.type === 'agent_guide' ? (
                    <div>
                      <div style={{marginBottom: '15px'}}>
                        {(message.content || '').toString().split('\n').map((line, i) => (
                          <div key={i} style={{marginBottom: '5px'}}>{line}</div>
                        ))}
                      </div>
                      {message.example_questions && (
                        <div style={{marginTop: '20px'}}>
                          <div style={{fontWeight: 'bold', marginBottom: '10px', color: '#4a5568'}}>
                            💡 예시 질문 클릭하여 사용:
                          </div>
                          <div style={{display: 'flex', flexDirection: 'column', gap: '8px'}}>
                            {message.example_questions.map((example, idx) => (
                              <button
                                key={idx}
                                onClick={() => {
                                  setInputValue(example);
                                  const frontendKey = agentKeyMapping[message.selected_agent] || message.selected_agent;
                                  setSelectedAgent(frontendKey);
                                }}
                                style={{
                                  textAlign: 'left',
                                  padding: '10px 15px',
                                  border: '1px solid #e2e8f0',
                                  borderRadius: '8px',
                                  backgroundColor: '#f7fafc',
                                  cursor: 'pointer',
                                  transition: 'all 0.2s',
                                  fontSize: '14px'
                                }}
                                onMouseEnter={(e) => {
                                  e.target.style.backgroundColor = '#edf2f7';
                                  e.target.style.borderColor = '#cbd5e0';
                                }}
                                onMouseLeave={(e) => {
                                  e.target.style.backgroundColor = '#f7fafc';
                                  e.target.style.borderColor = '#e2e8f0';
                                }}
                              >
                                {example}
                              </button>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  ) : message.type === 'agent_selection' ? (
                    <div>
                      <div style={{marginBottom: '15px'}}>
                        {(message.content || '').toString().split('\n').map((line, i) => (
                          <div key={i}>{line}</div>
                        ))}
                      </div>
                      <div style={{marginBottom: '10px', fontWeight: 'bold', color: '#666'}}>
                        다음 중 하나를 선택해주세요:
                      </div>
                      <div className="agent-selection-buttons">
                        {message.available_agents?.map((agentKey) => (
                          <button
                            key={agentKey}
                            className="agent-selection-btn"
                            onClick={() => handleAgentSelection(message.query, agentKey)}
                            disabled={isLoading}
                          >
                            <div className="agent-btn-title">
                              {message.agent_display_names?.[agentKey] || agentKey}
                            </div>
                            <div className="agent-btn-description">
                              {message.agent_descriptions?.[agentKey]?.substring(0, 100)}...
                            </div>
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : message.type === 'interactive' ? (
                    <div>
                      <div style={{marginBottom: '15px'}}>
                        {(message.content || '').toString().split('\n').map((line, i) => (
                          <div key={i}>{line}</div>
                        ))}
                      </div>
                      {message.waiting_for_input && (
                        <div style={{marginTop: '15px'}}>
                          {message.input_type === 'verification' && (
                            <div className="verification-buttons" style={{display: 'flex', gap: '10px'}}>
                              <button
                                onClick={() => {
                                  setInputValue('예');
                                  sendMessage();
                                }}
                                style={{
                                  padding: '8px 20px',
                                  backgroundColor: '#4CAF50',
                                  color: 'white',
                                  border: 'none',
                                  borderRadius: '5px',
                                  cursor: 'pointer'
                                }}
                                disabled={isLoading}
                              >
                                예
                              </button>
                              <button
                                onClick={() => {
                                  setInputValue('아니오');
                                  sendMessage();
                                }}
                                style={{
                                  padding: '8px 20px',
                                  backgroundColor: '#f44336',
                                  color: 'white',
                                  border: 'none',
                                  borderRadius: '5px',
                                  cursor: 'pointer'
                                }}
                                disabled={isLoading}
                              >
                                아니오
                              </button>
                            </div>
                          )}
                          {message.input_type === 'manual_selection' && message.options && (
                            <div style={{display: 'flex', flexDirection: 'column', gap: '8px'}}>
                              {message.options.map((option, idx) => (
                                <button
                                  key={idx}
                                  onClick={() => {
                                    setInputValue((idx + 1).toString());
                                    sendMessage();
                                  }}
                                  style={{
                                    textAlign: 'left',
                                    padding: '10px 15px',
                                    border: '1px solid #e2e8f0',
                                    borderRadius: '8px',
                                    backgroundColor: '#f7fafc',
                                    cursor: 'pointer',
                                    transition: 'all 0.2s'
                                  }}
                                  onMouseEnter={(e) => {
                                    e.target.style.backgroundColor = '#edf2f7';
                                    e.target.style.borderColor = '#cbd5e0';
                                  }}
                                  onMouseLeave={(e) => {
                                    e.target.style.backgroundColor = '#f7fafc';
                                    e.target.style.borderColor = '#e2e8f0';
                                  }}
                                  disabled={isLoading}
                                >
                                  {option}
                                </button>
                              ))}
                            </div>
                          )}
                          {message.input_type === 'data_input' && (
                            <div style={{
                              marginTop: '10px',
                              padding: '10px',
                              backgroundColor: '#f0f4f8',
                              borderRadius: '8px',
                              fontSize: '14px'
                            }}>
                              <div style={{color: '#555', marginBottom: '5px'}}>
                                📝 입력창에 필요한 정보를 입력해주세요
                              </div>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ) : (
                    (message.content || '').toString().split('\n').map((line, i) => (
                      <div key={i}>{line}</div>
                    ))
                  )}
                </div>
              </div>
            ))}
            
            {isLoading && (
              <div className="message ai-message">
                <div className="message-header">
                  <span className="message-sender">🤖 {agents[selectedAgent].name}</span>
                  <span className="message-time">처리 중...</span>
                </div>
                <div className="message-content">
                  <div className="typing-indicator">
                    처리 중<span>.</span><span>.</span><span>.</span>
                  </div>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          <div className="message-input-container">
            <div className="selected-agent-info">
              <span style={{ color: agents.router.color }}>
                ● {agents.router.name}
              </span>
              <span className="agent-description">
                질문에 따라 자동으로 적절한 에이전트가 선택됩니다
              </span>
            </div>
            <div className="input-area">
              <textarea
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyPress={handleKeyPress}
                placeholder={isWaitingForDocsInput ? 
                  (docsInputType === 'verification' ? "예/아니오로 답변해주세요" :
                   docsInputType === 'manual_selection' ? "번호를 입력해주세요 (1, 2, 3)" :
                   docsInputType === 'data_input' ? "필요한 정보를 입력해주세요" :
                   "응답을 입력해주세요") :
                  "인사정보/거래처분석/실적분석/문서분류 중에 질문해주세요."}
                disabled={isLoading}
                className="message-input"
                rows="1"
              />
              <button 
                onClick={sendMessage} 
                disabled={isLoading || !inputValue.trim()}
                className="send-button"
              >
                Send
              </button>
            </div>
          </div>
        </main>
        </div>
    </div>
  );
};

export default ChatScreen; 