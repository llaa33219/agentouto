# Provider Backends — 프로바이더 백엔드

이 문서는 프로바이더 시스템의 상세 동작, 파라미터 매핑, API별 특이사항을 설명한다.

---

## 1. 구조

```
Provider (데이터)          ProviderBackend (로직)
    │                          │
    ├── name                   ├── OpenAIBackend (Chat Completions)
    ├── kind ─────────────────→├── OpenAIResponsesBackend (Responses API)
    ├── api_key                ├── AnthropicBackend
    ├── base_url               └── GoogleBackend
    └── auth: AuthMethod | None
```

- `Provider`는 순수 데이터 (접속 정보만).
- `ProviderBackend`는 실제 LLM API 호출 로직.
- `Router`가 `Provider.kind`를 보고 적절한 `ProviderBackend`를 선택한다.
- 모든 백엔드는 `provider.api_key` 직접 접근 대신 `await provider.resolve_api_key()`를 사용한다. OAuth 토큰이 설정된 경우 자동으로 토큰을 반환한다.

---

## 2. 통일 파라미터 → API별 매핑

Agent에서 설정한 통일된 파라미터가 각 백엔드에서 어떻게 매핑되는지:

### `max_output_tokens`

| Agent 설정 | OpenAI Chat Completions | OpenAI Responses | Anthropic API | Google API |
|---|---|---|---|---|
| `max_output_tokens=None` (기본값) | 파라미터 **생략** → API가 모델 최대값 자동 적용 | 파라미터 **생략** → API가 모델 최대값 자동 적용 | **probe trick**으로 최대값 자동 탐색 (하단 참조) | 파라미터 **생략** → API가 모델 최대값 자동 적용 |
| `max_output_tokens=8192` | `max_completion_tokens=8192` | `max_output_tokens=8192` | `max_tokens=8192` | `max_output_tokens=8192` (generation_config 내) |

### `reasoning` + `reasoning_effort`

| Agent 설정 | OpenAI Chat Completions | OpenAI Responses | Anthropic API | Google API |
|---|---|---|---|---|
| `reasoning=True` | `reasoning_effort={value}` | `reasoning={"effort": value}` | `thinking={"type": "enabled", "budget_tokens": ...}` | `thinking_config={"thinking_budget": ...}` |
| `reasoning=False` | (생략) | (생략) | (생략) | (생략) |

### `reasoning_budget`

| Agent 설정 | OpenAI Chat Completions | OpenAI Responses | Anthropic API | Google API |
|---|---|---|---|---|
| `reasoning_budget=10240` | (해당 없음) | (해당 없음) | `thinking.budget_tokens=10240` | `thinking_config.thinking_budget=10240` |
| `reasoning_budget=None` | (해당 없음) | (해당 없음) | 기본값 4096 | 기본값 4096 |

### `temperature`

| Agent 설정 | OpenAI (Chat/Responses) | Anthropic | Google |
|---|---|---|---|
| `reasoning=True` | **전송하지 않음** | **강제로 1** | 그대로 전송 |
| `reasoning=False` | 그대로 전송 | 그대로 전송 | 그대로 전송 |

⚠️ **중요 규칙:**
- **OpenAI**: reasoning 모드에서는 temperature를 전송하면 안 된다. API 에러 발생.
- **Anthropic**: extended thinking 활성화 시 temperature는 반드시 1이어야 한다. API 강제 요구사항.

### `extra`

`Agent.extra` dict는 각 백엔드에서 API 호출 파라미터에 `**agent.extra`로 풀어서 전달된다. 프로바이더 특정 파라미터를 전달하는 데 사용할 수 있다.

---

## 3. OpenAI Chat Completions 백엔드 (`providers/openai.py`)

### 클라이언트 캐싱

```python
class OpenAIBackend:
    _clients: dict[str, tuple[str, AsyncOpenAI]]  # provider.name → (api_key, 클라이언트)

    def _get_client(provider, api_key) -> AsyncOpenAI
```

provider.name 기준으로 `(api_key, AsyncOpenAI)` 튜플을 캐싱한다. OAuth 토큰이 갱신되어 api_key가 변경되면 클라이언트를 새로 생성한다. `call()`/`stream()`에서 `await provider.resolve_api_key()`로 토큰을 해결한 후 전달한다.

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

### tool_call arguments 파싱 (`_parse_tool_arguments`)

`_parse_tool_arguments(raw)` 함수로 안전하게 파싱한다. 항상 `dict`를 반환한다:

1. `json.loads(raw)` 시도
2. 실패 시 마크다운 코드펜스 제거 (` ```json ... ``` `)
3. 실패 시 `_repair_incomplete_json(text)`로 불완전 JSON 복구 (닫는 괄호/따옴표 추가)
4. 최종 실패 시 `{}` 반환 + 경고 로그

⚠️ **이전 방식 (`{"raw": ...}` 폴백)의 문제점:** `{"raw": ...}`가 context에 저장되면 다음 LLM 호출 시 `json.dumps({"raw": ...})`로 전송되어 LLM이 이 패턴을 학습/반복하는 피드백 루프가 발생했다. `{}` 폴백은 도구가 자연스러운 에러 (누락된 파라미터)를 반환하여 LLM이 재시도할 수 있도록 한다.

### 에러 처리

모든 API 호출을 `try/except`로 감싸고 `ProviderError`로 래핑. 빈 응답 (choices 없음)도 `ProviderError` 발생.

### 멀티모달 첨부파일 처리

`_build_messages`에서 `ContextMessage.attachments`가 있으면 `content`를 multipart 배열로 변환:

| mime_type | OpenAI content part 타입 | 구조 |
|---|---|---|
| `image/*` | `image_url` | `{"type": "image_url", "image_url": {"url": data_uri_or_url}}` |
| `audio/*` | `input_audio` | `{"type": "input_audio", "input_audio": {"data": base64, "format": fmt}}` |

user 메시지와 tool 메시지 모두에서 첨부파일 처리. 첨부파일이 없으면 기존과 동일한 문자열 content 사용.

---

## 4. Anthropic 백엔드 (`providers/anthropic.py`)

### 클라이언트 캐싱

`_clients: dict[str, tuple[str, AsyncAnthropic]]` — provider.name 기준으로 `(api_key, client)` 튜플 캐싱. OAuth 토큰 변경 시 클라이언트 재생성. `call()`/`stream()`에서 `await provider.resolve_api_key()`로 토큰을 해결한 후 전달.

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

### 응답 파싱 (스트리밍 기반)

`call()`과 `stream()` 모두 내부적으로 스트리밍 API (`stream=True`)를 사용한다. 공유 `_stream_response()` 제너레이터가 스트리밍 이벤트를 처리한다:

- `content_block_start` (tool_use) → 도구 블록 등록 (id, name)
- `content_block_delta` (text_delta) → 텍스트 누적 + yield
- `content_block_delta` (input_json_delta) → 도구 입력 JSON 누적
- 스트림 종료 시 → 누적된 JSON을 `json.loads()`로 파싱하여 ToolCall 생성

`call()`은 `_stream_response()`를 소비하고 최종 `LLMResponse`만 반환한다.
`stream()`은 `_stream_response()`를 그대로 re-yield한다 (텍스트 청크 실시간 전달).

⚠️ **왜 `call()`도 스트리밍인가?** Anthropic SDK는 10분 이상 걸릴 수 있는 요청에 스트리밍을 **강제**한다. 비스트리밍 `create()`는 타임아웃 에러를 발생시킨다.

### Auto Max Tokens (Probe Trick)

Anthropic API는 `max_tokens`가 **필수 파라미터**이므로 생략할 수 없다. `agent.max_output_tokens`가 `None`이면 다음 절차로 최대값을 자동 탐색한다:

1. `_PROBE_MAX_TOKENS = 999_999_999` (터무니없이 큰 값)로 API 호출 시도
2. API가 에러 반환: `"max_tokens: 999999999 > 64000, which is the maximum allowed ..."`
3. `_parse_max_tokens_from_error(error_msg)`로 에러 메시지에서 실제 최대값 파싱 (2단계 정규식: `> (\d+),` → `\bis\s+(\d+)`)
4. 파싱된 최대값을 `_max_tokens_cache[model]`에 캐시
5. 캐시된 값으로 재시도

**캐싱 동작:**
- 파싱 성공 시만 캐시 (네트워크/인증 에러 시는 캐시하지 않음)
- probe가 성공하면 (모델이 999M 허용) 그 값 캐시
- `agent.max_output_tokens`가 명시적으로 설정되면 probe 건너뛰고 그대로 사용
- 비-max_tokens 에러 (인증 실패 등)는 즉시 raise

```python
_max_tokens_cache: dict[str, int] = {}  # 모델명 → 최대 토큰
_PROBE_MAX_TOKENS = 999_999_999
_DEFAULT_MAX_TOKENS = 8192  # 파싱 실패 시 안전한 기본값
```

### Extended Thinking

```python
if agent.reasoning:
    params["thinking"] = {
        "type": "enabled",
        "budget_tokens": agent.reasoning_budget or 4096,
    }
    params["temperature"] = 1  # 필수
```

### 멀티모달 첨부파일 처리

`_build_messages`에서 `ContextMessage.attachments`가 있으면 content blocks 배열로 변환:

| mime_type | Anthropic content block 타입 | source 타입 |
|---|---|---|
| `image/*` | `image` | `base64` (data) 또는 `url` (url) |
| `application/pdf` | `document` | `base64` (data) 또는 `url` (url) |

user 메시지: content blocks 배열로 변환 (`[{"type": "text", ...}, {"type": "image", ...}]`).
tool result: tool_result 내 content 배열에 첨부파일 블록 포함.

---

## 5. OpenAI Responses API 백엔드 (`providers/openai_responses.py`)

### 클라이언트 캐싱

`_clients: dict[str, tuple[str, AsyncOpenAI]]` — provider.name 기준으로 `(api_key, client)` 튜플 캐싱. Chat Completions 백엔드와 동일한 `AsyncOpenAI` 클라이언트 사용. OAuth 토큰 변경 시 클라이언트 재생성. `call()`/`stream()`에서 `await provider.resolve_api_key()`로 토큰을 해결한 후 전달.

### 메시지 변환 (`_build_input`)

Context → Responses API input items 포맷:

| Context 역할 | Responses API 구조 |
|---|---|
| system_prompt | `instructions` 파라미터로 별도 전달 (input 밖) |
| user | `{"role": "user", "content": ...}` |
| assistant (텍스트) | `{"role": "assistant", "content": ...}` |
| assistant (tool_calls) | 각 tool_call마다 `{"type": "function_call", "call_id": ..., "name": ..., "arguments": ...}` |
| tool (결과) | `{"type": "function_call_output", "call_id": ..., "output": ...}` |

❗ **중요:**
- system prompt는 input이 아닌 `instructions` 파라미터로 전달한다.
- assistant의 tool_calls는 각각 독립적인 `function_call` 아이템으로 변환한다.
- tool 결과는 `function_call_output` 아이템으로 `call_id`로 매핑한다.
- `previous_response_id`는 사용하지 않는다 (매 호출마다 전체 input 전송, 스테이트리스 모드).

### 도구 스키마 변환 (`_build_tools`)

```python
[{"type": "function", "name": ..., "description": ..., "parameters": ...}]
```

Chat Completions의 이중 래핑 (`{"type": "function", "function": {...}}`)과 달리 플랫 구조이다.

### 응답 파싱

- `response.output` 리스트에서 `type=="function_call"` 아이템의 `call_id`, `name`, `arguments` 추출
- `response.output_text`로 텍스트 content 추출
- `_parse_tool_arguments`는 `providers/openai.py`에서 재사용 (import)

### 스트리밍

`stream=True`로 호출 후 SSE 이벤트 처리:
- `response.output_text.delta` → 텍스트 청크
- `response.output_item.added` (function_call) → 도구 호출 등록
- `response.function_call_arguments.delta` → 도구 인자 청크 누적
- 스트림 종료 시 → 누적된 인자를 파싱하여 ToolCall 생성

### `previous_response_id` — 사용하지 않음

현재 아키텍처는 매 `_run_agent_loop` 호출마다 독립적인 Context를 생성한다. `previous_response_id`를 사용하면 서버 상태와 Context 이중 관리 문제가 발생한다. 따라서 매 호출마다 전체 input을 전송하는 스테이트리스 모드로 사용한다. 사용자가 원하면 `Agent.extra["previous_response_id"]`로 직접 전달 가능.

### 멀티모달 첨부파일 처리

`_build_input`에서 `ContextMessage.attachments`가 있으면 content 배열로 변환:

| mime_type | Responses API content part 타입 | 구조 |
|---|---|---|
| `image/*` | `input_image` | `{"type": "input_image", "image_url": data_uri_or_url}` |
| `audio/*` | `input_audio` | `{"type": "input_audio", "data": base64, "format": fmt}` |

user 메시지에서 첨부파일 처리. 텍스트는 `input_text` 타입으로 변환.

---

## 6. Google Gemini 백엔드 (`providers/google.py`)

### 클라이언트 설정

`genai.configure(api_key=...)` — 전역 설정이므로 `_configured: dict[str, str]`로 API 키 변경 감지. OAuth 토큰이 갱신되면 `genai.configure()`를 다시 호출한다. `call()`/`stream()`에서 `await provider.resolve_api_key()`로 토큰을 해결한 후 전달.

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

### 멀티모달 첨부파일 처리

`_build_contents`에서 `ContextMessage.attachments`가 있으면 Part 객체를 추가:

| 데이터 소스 | Google Part 타입 | 구조 |
|---|---|---|
| `data` (base64) | `inline_data` | `Part(inline_data=Blob(mime_type=..., data=base64.b64decode(...)))` |
| `url` | `file_data` | `Part(file_data=FileData(mime_type=..., file_uri=...))` |

user 메시지: text Part 뒤에 첨부파일 Part 추가.
tool 결과: function_response Part 뒤에 첨부파일 Part 추가.

Google 백엔드는 mime_type을 필터링하지 않으므로 모든 파일 타입 (이미지, 오디오, 비디오 등)을 지원한다.

---

## 7. 새 프로바이더 추가 시

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
- [ ] `max_output_tokens` 매핑 (`None` 시 자동 최대값 처리)
- [ ] `reasoning` / `reasoning_effort` / `reasoning_budget` 매핑
- [ ] `temperature` 특수 처리 (있는 경우)
- [ ] API 에러 → `ProviderError` 래핑
- [ ] 빈 응답 처리
- [ ] tool_call arguments 파싱 (안전한 방식 — `{"raw": ...}` 폴백 금지, `{}` 폴백 사용)
- [ ] tool_call ID 처리
- [ ] 멀티모달 첨부파일 처리 (`_build_messages`에서 user/tool 메시지의 attachments 변환)
- [ ] `resolve_api_key()` 사용 (`provider.api_key` 직접 접근 금지)

---

## 8. 알려진 제한사항

1. **Google 전역 설정**: `genai.configure()`가 전역이므로 여러 Google Provider를 동시에 사용하면 충돌 가능.
2. **스트리밍 부분 지원**: OpenAI (Chat Completions + Responses), Anthropic 백엔드는 네이티브 스트리밍 구현. Google은 fallback (non-streaming 호출 후 단일 이벤트 반환).
3. **멀티모달 프로바이더별 지원 범위**: 프로바이더별로 지원하는 첨부파일 타입이 다르다. OpenAI는 image/audio, Anthropic은 image/PDF, Google은 모든 타입. 지원되지 않는 mime_type의 첨부파일은 조용히 무시된다.
4. **Anthropic max_tokens probe 레이스 컨디션**: 동일 모델에 대한 동시 호출 시 여러 번 probe가 실행될 수 있다. 첫 번째 성공 후 캐시되므로 이후는 발생하지 않는다.
