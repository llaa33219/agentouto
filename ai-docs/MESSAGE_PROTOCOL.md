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
      "message": {"type": "string", "description": "Message to send to the agent"}
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
  "description": "Finish the current task and return a result to the caller. The caller may be a user or another agent.",
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

### 텍스트 응답 폴백

LLM이 `finish`를 호출하지 않고 도구 호출 없이 텍스트만 응답한 경우:
- `response.tool_calls`가 비어있으면 `response.content`를 반환값으로 사용
- 이는 LLM이 명시적으로 `finish`를 호출하지 않아도 동작하게 하는 안전장치

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
    │      ├── tool_calls 없음     → content 반환 → 루프 종료
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

1. `finish` 도구 호출 → 명시적 종료
2. 도구 호출 없이 텍스트 응답 → 암시적 종료

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

Available agents:
- writer: 글을 잘 쓰는 작가.
- reviewer: 품질 검토 전문가.

Use call_agent to delegate work to other agents.
Use finish to complete your task and return the result.
```

### 포함되는 정보

1. 에이전트 자신의 이름과 instructions
2. 다른 에이전트 목록 (현재 에이전트 제외) — 이름과 instructions
3. call_agent / finish 사용 안내

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
