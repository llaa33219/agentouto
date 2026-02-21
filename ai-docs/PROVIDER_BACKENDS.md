# Provider Backends — 프로바이더 백엔드

이 문서는 프로바이더 시스템의 상세 동작, 파라미터 매핑, API별 특이사항을 설명한다.

---

## 1. 구조

```
Provider (데이터)          ProviderBackend (로직)
    │                          │
    ├── name                   ├── OpenAIBackend
    ├── kind ─────────────────→├── AnthropicBackend
    ├── api_key                └── GoogleBackend
    └── base_url
```

- `Provider`는 순수 데이터 (접속 정보만).
- `ProviderBackend`는 실제 LLM API 호출 로직.
- `Router`가 `Provider.kind`를 보고 적절한 `ProviderBackend`를 선택한다.

---

## 2. 통일 파라미터 → API별 매핑

Agent에서 설정한 통일된 파라미터가 각 백엔드에서 어떻게 매핑되는지:

### `max_output_tokens`

| Agent 설정 | OpenAI API | Anthropic API | Google API |
|---|---|---|---|
| `max_output_tokens=8192` | `max_completion_tokens=8192` | `max_tokens=8192` | `max_output_tokens=8192` (generation_config 내) |

### `reasoning` + `reasoning_effort`

| Agent 설정 | OpenAI API | Anthropic API | Google API |
|---|---|---|---|
| `reasoning=True` | `reasoning_effort={value}` | `thinking={"type": "enabled", "budget_tokens": ...}` | `thinking_config={"thinking_budget": ...}` |
| `reasoning=False` | (생략) | (생략) | (생략) |

### `reasoning_budget`

| Agent 설정 | OpenAI API | Anthropic API | Google API |
|---|---|---|---|
| `reasoning_budget=10240` | (해당 없음) | `thinking.budget_tokens=10240` | `thinking_config.thinking_budget=10240` |
| `reasoning_budget=None` | (해당 없음) | 기본값 4096 | 기본값 4096 |

### `temperature`

| Agent 설정 | OpenAI | Anthropic | Google |
|---|---|---|---|
| `reasoning=True` | **전송하지 않음** | **강제로 1** | 그대로 전송 |
| `reasoning=False` | 그대로 전송 | 그대로 전송 | 그대로 전송 |

⚠️ **중요 규칙:**
- **OpenAI**: reasoning 모드에서는 temperature를 전송하면 안 된다. API 에러 발생.
- **Anthropic**: extended thinking 활성화 시 temperature는 반드시 1이어야 한다. API 강제 요구사항.

### `extra`

`Agent.extra` dict는 각 백엔드에서 API 호출 파라미터에 `**agent.extra`로 풀어서 전달된다. 프로바이더 특정 파라미터를 전달하는 데 사용할 수 있다.

---

## 3. OpenAI 백엔드 (`providers/openai.py`)

### 클라이언트 캐싱

```python
class OpenAIBackend:
    _clients: dict[str, AsyncOpenAI]  # provider.name → 클라이언트

    def _get_client(provider) -> AsyncOpenAI
```

provider.name 기준으로 `AsyncOpenAI` 인스턴스를 캐싱한다. 같은 프로바이더에 대한 반복 호출 시 클라이언트를 재사용한다.

### 메시지 변환 (`_build_messages`)

Context → OpenAI 메시지 포맷:

| Context 역할 | OpenAI 역할 | 구조 |
|---|---|---|
| system_prompt | `{"role": "system", "content": ...}` | 첫 번째 메시지 |
| user | `{"role": "user", "content": ...}` | |
| assistant (텍스트) | `{"role": "assistant", "content": ...}` | |
| assistant (tool_calls) | `{"role": "assistant", "content": ..., "tool_calls": [...]}` | tool_calls에 function name/arguments 포함 |
| tool | `{"role": "tool", "tool_call_id": ..., "content": ...}` | |

### 도구 스키마 변환 (`_build_tools`)

```python
[{"type": "function", "function": {name, description, parameters}}]
```

### tool_call arguments 파싱

`json.loads(tc.function.arguments)` — 파싱 실패 시 `{"raw": original_string}`으로 폴백.

### 에러 처리

모든 API 호출을 `try/except`로 감싸고 `ProviderError`로 래핑. 빈 응답 (choices 없음)도 `ProviderError` 발생.

---

## 4. Anthropic 백엔드 (`providers/anthropic.py`)

### 클라이언트 캐싱

`_clients: dict[str, AsyncAnthropic]` — provider.name 기준 캐싱.

### 메시지 변환 (`_build_messages`)

Anthropic은 OpenAI와 다른 구조를 사용한다:

| Context 역할 | Anthropic 구조 |
|---|---|
| system_prompt | `system` 파라미터로 별도 전달 (messages 밖) |
| user | `{"role": "user", "content": "text"}` |
| assistant (텍스트) | `{"role": "assistant", "content": [{"type": "text", "text": ...}]}` |
| assistant (tool_calls) | `{"role": "assistant", "content": [{"type": "text"...}, {"type": "tool_use", "id":..., "name":..., "input":...}]}` |
| tool (결과) | `{"role": "user", "content": [{"type": "tool_result", "tool_use_id":..., "content":...}]}` |

⚠️ **중요:**
- 연속된 tool result 메시지는 하나의 `user` 메시지로 묶어야 한다 (배열로).
- system prompt는 messages가 아닌 `system` 파라미터로 전달한다.
- tool_use의 `input`은 이미 dict이다 (JSON 문자열이 아님).

### 도구 스키마 변환 (`_build_tools`)

```python
[{"name": ..., "description": ..., "input_schema": ...}]
```

OpenAI의 `parameters` → Anthropic의 `input_schema`.

### 응답 파싱

응답의 `content` 블록을 순회하며:
- `type == "text"` → content_text
- `type == "tool_use"` → ToolCall (id, name, input을 arguments로)

### Extended Thinking

```python
if agent.reasoning:
    params["thinking"] = {
        "type": "enabled",
        "budget_tokens": agent.reasoning_budget or 4096,
    }
    params["temperature"] = 1  # 필수
```

---

## 5. Google Gemini 백엔드 (`providers/google.py`)

### 클라이언트 설정

`genai.configure(api_key=...)` — 전역 설정이므로 `_configured: set[str]`로 중복 호출 방지.

⚠️ **주의:** `google-generativeai` 패키지는 전역 설정을 사용한다. 여러 Google Provider를 동시에 사용하면 마지막 `configure` 호출이 이전 것을 덮어쓸 수 있다. 현재 알려진 제한사항.

### 메시지 변환 (`_build_contents`)

`genai.protos`를 사용한 protobuf 기반 구조:

| Context 역할 | Google 구조 |
|---|---|
| system_prompt | `GenerativeModel(system_instruction=...)` |
| user | `Content(role="user", parts=[Part(text=...)])` |
| assistant | `Content(role="model", parts=[Part(text=...), Part(function_call=...)])` |
| tool (결과) | `Content(role="function", parts=[Part(function_response=...)])` |

⚠️ **중요:**
- assistant 역할 → `"model"` 로 변환.
- tool 결과 역할 → `"function"` 으로 변환.
- 연속된 tool result는 하나의 `function` Content로 묶는다.
- function_response의 response는 `{"result": content}` dict 형태.

### JSON Schema → Google Schema 변환 (`_json_schema_to_google`)

JSON Schema 타입을 Google의 enum 타입으로 매핑:

```python
_JSON_TYPE_MAP = {
    "string": 1, "number": 2, "integer": 3,
    "boolean": 4, "array": 5, "object": 6,
}
```

재귀적으로 properties를 변환한다.

### tool_call ID

Google API는 function_call에 ID를 제공하지 않으므로 `uuid.uuid4().hex`로 자체 생성한다.

### Thinking Config

```python
if agent.reasoning:
    gen_config["thinking_config"] = {
        "thinking_budget": agent.reasoning_budget or 4096,
    }
```

---

## 6. 새 프로바이더 추가 시

1. `providers/newkind.py` 생성
2. `ProviderBackend`를 상속하여 `call()` 구현
3. `providers/__init__.py`의 `get_backend()`에 분기 추가
4. `provider.py`의 `kind` Literal에 새 값 추가
5. 이 문서(`PROVIDER_BACKENDS.md`)에 새 섹션 추가
6. `ARCHITECTURE.md` 패키지 구조 업데이트

### 구현 체크리스트

- [ ] `ProviderBackend.call()` 구현
- [ ] Context → API 포맷 변환 함수
- [ ] 도구 스키마 변환 함수
- [ ] 클라이언트 캐싱
- [ ] `max_output_tokens` 매핑
- [ ] `reasoning` / `reasoning_effort` / `reasoning_budget` 매핑
- [ ] `temperature` 특수 처리 (있는 경우)
- [ ] API 에러 → `ProviderError` 래핑
- [ ] 빈 응답 처리
- [ ] tool_call arguments 파싱 (안전한 방식)
- [ ] tool_call ID 처리

---

## 7. 알려진 제한사항

1. **Google 전역 설정**: `genai.configure()`가 전역이므로 여러 Google Provider를 동시에 사용하면 충돌 가능.
2. **스트리밍 부분 지원**: OpenAI 백엔드만 네이티브 스트리밍 구현. Anthropic, Google은 fallback (non-streaming 호출 후 단일 이벤트 반환).
3. **비전/멀티모달 미지원**: 텍스트 기반 호출만 지원. 이미지 등의 멀티모달 입력은 미구현.
