# Message Protocol — 메시지 프로토콜

이 문서는 메시지 타입, 라우팅 규칙, 에이전트 루프, 병렬 호출 메커니즘을 설명한다.

---

## 1. 메시지 타입

메시지는 **2종류만** 존재한다:

### 전달 메시지 (Forward)

호출자 → 피호출자에게 보내는 메시지.

```python
Message(type="forward", sender="researcher", receiver="writer", content="이 정보로 보고서 작성해줘: ...")
```

### 반환 메시지 (Return)

피호출자 → 호출자에게 돌려보내는 응답.

```python
Message(type="return", sender="writer", receiver="researcher", content="보고서: ...")
```

### 규칙

1. **반환은 항상 호출한 에이전트에게만 돌아간다.** 호출자 ≠ 수신자인 경우는 존재하지 않는다.
2. **새로운 메시지 타입은 존재하지 않는다.** 추가하지 마라.

---

## 2. 구현 상태

런타임은 매 에이전트 호출/반환 시점에 `Message` 객체를 생성하여 추적한다:

- **전달 메시지**: `_run_agent_loop` 진입 시 `Message(type="forward", sender=caller, receiver=agent, content=message, attachments=attachments)` 생성
- **반환 메시지**: 에이전트 루프 종료 시 `Message(type="return", sender=agent, receiver=caller, content=result)` 생성

모든 메시지는 `RunResult.messages`에 수집되며, `debug` 모드와 무관하게 항상 기록된다. 각 메시지는 `uuid4` 기반의 `call_id`로 고유하게 식별된다. `attachments` 필드는 멀티모달 첨부파일을 포함하며, 없으면 `None`이다.

---

## 3. call_agent — 에이전트 호출

LLM에게 제공되는 `call_agent` 도구:

```json
{
  "name": "call_agent",
  "description": "Call another agent. The agent will process your message and return a result when done.",
  "parameters": {
    "type": "object",
    "properties": {
      "agent_name": {"type": "string", "description": "Name of the agent to call"},
      "message": {"type": "string", "description": "Message to send to the agent"},
      "history": {
        "type": "array",
        "description": "Optional conversation history to attach (from previous RunResult.messages)",
        "items": {
          "type": "object",
          "properties": {
            "type": {"type": "string", "enum": ["forward", "return"]},
            "sender": {"type": "string"},
            "receiver": {"type": "string"},
            "content": {"type": "string"}
          },
          "required": ["type", "sender", "receiver", "content"]
        }
      }
    },
    "required": ["agent_name", "message"]
  }
}
```

### 동작

1. LLM이 `call_agent(agent_name="writer", message="...")` 호출
2. Runtime이 `_execute_tool_call` 에서 처리
3. 대상 에이전트(`writer`)의 `_run_agent_loop` 재귀 호출
4. 대상 에이전트가 완료되면 결과 문자열을 도구 결과로 반환
5. 호출한 에이전트의 context에 도구 결과로 추가
6. `history` 파라미터가 있으면 해당 메시지를 에이전트의 컨텍스트 앞에 추가

### 핵심: call_agent = 재귀 호출

```python
async def _execute_tool_call(self, tc: ToolCall) -> str:
    if tc.name == CALL_AGENT:
        target = self._router.get_agent(tc.arguments["agent_name"])
        return await self._run_agent_loop(target, tc.arguments["message"])
    ...
```

각 `call_agent` 호출은 독립적인 Context를 가진 새로운 에이전트 루프 인스턴스다.

---

## 4. finish — 작업 완료

LLM에게 제공되는 `finish` 도구:

```json
{
  "name": "finish",
  "description": "Return your final result to the caller. This is the ONLY way to deliver your response — plain text is not delivered. Always use this tool when you are done.",
  "parameters": {
    "type": "object",
    "properties": {
      "message": {"type": "string", "description": "Result message to return"}
    },
    "required": ["message"]
  }
}
```

### 동작

1. LLM이 `finish(message="최종 결과: ...")` 호출
2. Runtime이 `_find_finish`로 감지
3. `finish.arguments["message"]`를 반환값으로 사용
4. 에이전트 루프 종료

### finish 강제 (Finish Nudge)

LLM이 `finish`를 호출하지 않고 도구 호출 없이 텍스트만 응답한 경우:
- 해당 텍스트를 context에 assistant 메시지로 추가
- "plain text는 전달되지 않았다, finish를 사용하라"는 안내를 user 메시지로 추가
- 루프를 재시도하여 LLM이 `finish()`를 호출할 때까지 계속 유도
- 재시도 횟수 제한 없음 — 철학에 따라 시스템 레벨 제한을 두지 않음

이 메커니즘은 에이전트의 **일반 메시지 출력**과 **명시적 반환값**을 명확히 분리한다. `RunResult.output`은 항상 `finish(message=...)` 로 명시적으로 결정된 값이다.

---

## 5. 에이전트 루프

```
[에이전트 호출됨 — forward message 수신]
         │
         ▼
    ┌─→ LLM 호출 (router.call_llm)
    │      │
    │      ▼
    │   LLM 응답 분석
    │      │
    │      ├── tool_calls 없음     → finish nudge (제한 없이 재시도)
    │      ├── finish 포함          → finish.message 반환 → 루프 종료
    │      └── tool_calls 있음     → asyncio.gather로 병렬 실행
    │                                    │
    │                                    ├── call_agent → 재귀 호출
    │                                    └── 일반 도구 → tool.execute()
    │                                    │
    │                              결과를 context에 추가
    │                                    │
    └────────────────────────────────────┘
```

### 루프 종료 조건

1. `finish` 도구 호출 → 명시적 종료 (**유일한 종료 경로**)
2. 텍스트 전용 응답 → finish nudge 재시도 (제한 없음)

### 루프 내 상태

각 에이전트 루프 인스턴스는 독립적인 `Context`를 가진다:
- `system_prompt`: Router가 생성 (에이전트 이름, instructions, 다른 에이전트 목록)
- `messages`: 루프 내에서 누적 (user, assistant, tool 메시지)

같은 에이전트가 여러 번 호출되어도 각 호출은 별도의 Context를 가진다.

---

## 6. 병렬 호출

LLM이 한 번의 응답에서 여러 tool_calls를 반환하면, Runtime은 이를 병렬로 실행한다.

### 메커니즘

```python
tasks = [self._execute_tool_call(tc) for tc in response.tool_calls]
results = await asyncio.gather(*tasks, return_exceptions=True)
```

### 에러 내성

`return_exceptions=True`로 호출하므로:
- 성공한 호출: 결과 문자열
- 실패한 호출: `"Error: {exception}"` 문자열로 변환

에러가 발생해도 다른 호출에 영향을 주지 않고, LLM이 에러 메시지를 보고 대응할 수 있다.

### 예시

LLM이 한 번에 3개의 call_agent를 호출하면:

```
Agent A의 LLM 응답:
  tool_calls: [
    call_agent(agent_name="B", message="..."),
    call_agent(agent_name="C", message="..."),
    call_agent(agent_name="D", message="..."),
  ]

→ asyncio.gather(
    _run_agent_loop(B, "..."),
    _run_agent_loop(C, "..."),
    _run_agent_loop(D, "..."),
  )

→ 3개 에이전트가 동시에 실행
→ 전부 완료되면 결과 3개를 context에 추가
→ Agent A의 LLM이 3개 결과를 한번에 보고 판단
```

---

## 7. 시스템 프롬프트 구조

Router가 자동 생성하는 시스템 프롬프트:

```
You are "{에이전트 이름}". {instructions}

INVOKED BY: {호출자}이(가) 당신을 호출했습니다.

Available agents:
- writer: 글을 잘 쓰는 작가.
- reviewer: 품질 검토 전문가.

PARALLEL EXECUTION:
- 여러 에이전트를 한 번에 부르려면 응답 하나에 여러 call_agent 도구 호출을 포함하세요
- 여러 에이전트를 동시에 호출하면 병렬로 실행됩니다 - 순차보다 훨씬 빠릅니다
- 예: 응답 하나에 3개의 call_agent 호출 = 3개의 에이전트가 동시에 작업

COLLABORATION GUIDELINES:
- 다른 에이전트와 협력하는 데 열정적이어야 합니다
- 역할을 정확히 따르세요 - 정의된 목적과 전문성을 유지하세요
- 협력 요청 시 적극적으로 참여하고 최선의 기여를하세요
- 결과가 개선되면 다른 에이전트에게 작업을 위임하세요
- 건설적인 피드백을 제공하여 다른 에이전트의 작업을 도와주세요

IMPORTANT: You MUST call the finish tool to return your final result. Plain text responses are NOT delivered to the caller — only finish(message="...") will be received. Never respond with plain text when you are done.
Use call_agent to delegate work to other agents.
```

### 포함되는 정보

1. 에이전트 자신의 이름과 instructions
2. 호출자 정보 (누가 호출했는지)
3. 다른 에이전트 목록 (현재 에이전트 제외) — 이름과 instructions
4. 병렬 실행 가이드
5. 협업 가이드라인
6. finish 메커니즘 안내 (plain text 비전달 설명)
7. call_agent 사용 안내

### 제외되는 정보

- 도구 설명 (도구 스키마로 별도 전달)
- 호출 제한 안내 (제한이 없으므로)
- 프로바이더/모델 정보 (에이전트에게 불필요)

---

## 8. 사용자 = LLM 없는 에이전트

사용자가 `run(entry=researcher, message="...", attachments=[...])` 을 호출하면:

1. 내부적으로 `_run_agent_loop(researcher, "...", attachments=[...])` 호출
2. 이는 에이전트가 `call_agent(agent_name="researcher", message="...")` 하는 것과 **완전히 동일한 코드 경로**
3. 반환값도 동일 — 문자열
4. `attachments`는 첨부파일 데이터를 전달하는 선택적 keyword-only 파라미터

사용자를 위한 별도의 코드 경로, 도구, 프로토콜, 특별 처리는 존재하지 않으며, 앞으로도 추가해서는 안 된다.

---

## 9. 자기 호출 / 순환 호출

각 `call_agent` 호출은 독립적인 `_run_agent_loop` 인스턴스이므로:

```
A(call_agent B) → B(call_agent A) → A(call_agent A) → A(finish) → A(finish) → B(finish) → A(finish)
```

각 `→`는 독립적인 Context를 가진 별도의 루프 인스턴스다. 같은 이름의 에이전트라도 각 호출은 독립적이다.

시스템 레벨에서 이를 차단하지 않는다. LLM의 `instructions`로 자연어 제어만 가능하다.

---

## 11. 백그라운드 실행 — Background Execution

에이전트를 백그라운드에서 실행하고 다른 루프의 에이전트와 통신할 수 있다.

### 백그라운드 에이전트 스폰

`call_agent`에 `background=True`를 사용하거나 `run_background()`公开 API를 사용:

```python
from agentouto import run_background

# 공개 API로 백그라운드 스폰
task_id = run_background(
    entry=writer,
    message="Write a report on AI trends.",
    agents=[writer, researcher],
    tools=[search_web],
    providers=[openai],
)
# task_id = "bg_abc123"

# 에이전트 내부에서 call_agent 사용
call_agent(agent_name="writer", message="...", background=True)
→ "Background agent started. Task ID: bg_abc123"
```

### 메시지 보내기 — send_message

실행 중인 에이전트에 메시지 주입:

```
send_message(task_id="bg_abc123", message="追加の指示")
→ "Message sent to writer (task_id: bg_abc123)"
```

에이전트는 받은 메시지를 사용자 입력으로 수신한다.

### 결과 조회 — get_agent_status

실행 중인 에이전트의 상태와 메시지 조회:

```
get_agent_status(task_id="bg_abc123")
→ "Task ID: bg_abc123
   Agent: writer
   Status: running
   Messages (3):
     [forward] user -> writer: ...
     [return] writer -> user: ..."
```

### 스트리밍 — get_stream_events

백그라운드 에이전트에서 스트리밍 events 수신:

```python
from agentouto import get_stream_events

async for event in get_stream_events("bg_abc123"):
    if event["type"] == "token":
        print(event["data"]["text"], end="", flush=True)
    elif event["type"] == "finish":
        print(f"\n--- Result: {event['data']['output']} ---")
```

### 격리된 루프 간 통신 다이어그램

```
[Agent A - Main Loop]
     │
     ├── call_agent(agent_name="B", background=True)
     │        │
     │        ▼ (non-blocking, returns task_id immediately)
     │
     │   [Agent B - Background Loop 1]
     │        │
     ├── send_message(task_id="bg_...", message="...")
     │        │  ← Message injected as user input
     │        ▼
     │   [Agent B receives message]
     │        │
     │        ▼
     │   get_messages(task_id="bg_...") → status, messages
     │
     └── continues working...


[Agent C - Background Loop 2] ← 다른 백그라운드 에이전트도 독립 실행
```

### 중요: 백그라운드 ≠ 비동기

백그라운드 에이전트는:
- 별도의 루프 인스턴스에서 실행
- 자신만의 Context 보유
- 다른 백그라운드 에이전트와 동시에 실행 가능
- `send_message`로 런타임에 메시지 주입 가능

기존 `asyncio.gather` 병렬 호출과의 차이:
- `asyncio.gather`: 같은 루프 iteration에서 여러 도구/에이전트를 동시 실행
- 백그라운드: 완전히 별개의 루프에서 독립적 에이전트 실행 + 통신 가능

### 메시지 주입 타이밍

`send_message`로 전송된 메시지는 **에이전트 루프의 다음 iteration 시작 시** 처리된다:

```
1. Agent Loop Iteration N: LLM Call → output → output → tool_calls → iteration ends
2. User calls send_message(task_id, "추가 요청") → message injected into queue
3. Agent Loop Iteration N+1: queue check → injected_msg found → context.add_user("추가 요청")
4. LLM이 기존 context + 새로운 메시지 포함해서 계속 진행 → output → output → finish
```

즉, LLM이 출력을 생성중일 때는interrupt되지 않고, 다음 iteration에서 자연스럽게 처리된다.

---

## 10. 병렬로 호출된 동일 이름 에이전트 추적

같은 이름의 에이전트가 여러 번 병렬로 호출되어도, 각 호출은 고유한 `call_id`로 구분된다.

### 추적 구조: 두 가지 수준

#### 수준 1: Message.call_id (항상 사용 가능)

모든 메시지는 `call_id`를 가지며, `RunResult.messages`에 항상 기록된다:

```python
@dataclass
class Message:
    type: Literal["forward", "return"]
    sender: str
    receiver: str
    content: str
    call_id: str  # uuid4 자동 생성 — 항상 고유
```

#### 수준 2: EventLog / Trace (debug=True 필요)

```python
@dataclass
class AgentEvent:
    event_type: EventType
    agent_name: str           # 에이전트 이름 (중복 가능)
    call_id: str              # 고유 식별자 — 실제 추적 키
    parent_call_id: str | None  # 부모 호출 ID (누가 호출했는지)
```

### 병렬 호출 예시

```
Agent A의 LLM 응답:
  tool_calls: [
    call_agent(agent_name="researcher", message="..."),  # sub_call_id = "abc123"
    call_agent(agent_name="researcher", message="..."),  # sub_call_id = "def456"
  ]

→ asyncio.gather로 동시 실행:
  _run_agent_loop(researcher, "abc123", parent="A의 call_id")
  _run_agent_loop(researcher, "def456", parent="A의 call_id")
```

두 "researcher"는 이름이 같지만:
- 첫 번째: `call_id="abc123"`, `parent_call_id="A의 call_id"`
- 두 번째: `call_id="def456"`, `parent_call_id="A의 call_id"`

### 추적 방법

#### 1. Message 목록에서 확인 (항상 가능)

```python
result = run(entry=a, ...)

for msg in result.messages:
    if msg.receiver == "researcher":
        print(f"call_id={msg.call_id[:8]} {msg.type}: {msg.content[:50]}")
```

#### 2. EventLog로 필터링 (debug=True 필요)

```python
result = run(entry=a, ..., debug=True)

# agent_name으로 필터 (같은 이름의 모든 호출)
events = result.event_log.filter(agent_name="researcher")
for e in events:
    print(f"{e.call_id[:8]} {e.event_type} {e.details}")

# event_type으로 필터
calls = result.event_log.filter(event_type="agent_call")
returns = result.event_log.filter(event_type="agent_return")
```

#### 3. Trace로 트리 시각화 (debug=True 필요)

```python
result = run(entry=a, ..., debug=True)
print(result.trace.print_tree())
```

출력 예시:
```
[a] (2.50s)
├── [researcher] (1.00s)       ← call_id=abc123...
│   └── ⚡ search_web
└── [researcher] (1.20s)       ← call_id=def456... (같은 이름이지만 별도 노드)
    └── ⚡ fetch_data
```

### 요약

| 추적 수준 | 데이터 | 항상 가능 | debug=True 필요 |
|-----------|--------|-----------|-----------------|
| Message.call_id | `RunResult.messages` | ✅ | ❌ |
| StreamEvent.call_id | streaming events | ✅ | ❌ |
| EventLog | `result.event_log` | ❌ | ✅ |
| Trace | `result.trace` | ❌ | ✅ |

**핵심 규칙**: `agent_name`이 아니라 `call_id`가 추적의 실제 키다.
