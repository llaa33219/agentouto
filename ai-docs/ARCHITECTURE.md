# Architecture — 아키텍처

이 문서는 AgentOutO의 패키지 구조, 모듈 책임, 클래스 관계, 데이터 흐름을 설명한다.

---

## 1. 패키지 구조

```
agentouto/
├── __init__.py          # 공개 API 엑스포트
├── _constants.py        # 내부 상수 (CALL_AGENT, FINISH)
├── agent.py             # Agent 데이터클래스
├── context.py           # 에이전트별 대화 컨텍스트 관리
├── event_log.py         # 구조화된 이벤트 로깅 (AgentEvent, EventLog)
├── exceptions.py        # 커스텀 예외 계층
├── auth/
│   ├── __init__.py      # AuthMethod ABC, TokenData, 공개 API 엑스포트
│   ├── api_key.py       # ApiKeyAuth (정적 API 키 래퍼)
│   ├── openai_oauth.py  # OpenAIOAuth (OpenAI OAuth 2.0 + PKCE)
│   ├── claude_oauth.py  # ClaudeOAuth (Anthropic OAuth, ⚠️ TOS 제한)
│   ├── google_oauth.py  # GoogleOAuth (Google OAuth, ⚠️ TOS 제한)
│   ├── token_store.py   # TokenStore (토큰 영속 저장)
│   └── _oauth_common.py # PKCE, 콜백 서버, 브라우저 인증, 토큰 교환
├── message.py           # Message 데이터클래스
├── model_metadata.py    # 모델 메타데이터 (context_window, max_output_tokens)
├── provider.py          # Provider 데이터클래스
├── router.py            # 메시지 라우팅, 시스템 프롬프트, 도구 스키마
├── loop_manager.py      # Background agent loops, message queues, registry
├── runtime.py           # 에이전트 루프 엔진, 병렬 실행, 스트리밍, run()/async_run()
├── streaming.py         # 스트리밍 인터페이스 (StreamEvent, async_run_stream)
├── summarizer.py        # 컨텍스트 요약 (토큰 추정, 경계 탐색, 요약 프롬프트 생성)
├── tool.py              # Tool 데코레이터/클래스
├── tracing.py           # 호출 트레이싱 (Span, Trace)
├── _bridge/             # coreouto 어댑터 (agentouto에서 coreouto를 import하는 유일한 곳)
│   ├── __init__.py      # run_agent_loop() — coreouto.Agent.call() 호출, 등록 부트스트랩
│   ├── convert.py       # 타입 변환 (Context ↔ Message, Attachment ↔ ContentBlock, Usage)
│   ├── state.py         # RunState + ContextVar (실행 단위 상태 바인딩)
│   ├── provider.py      # DispatchProvider (coreouto Provider 프로토콜 구현)
│   ├── tools.py         # builtin + 사용자 도구 디스패치, coreouto 도구 레지스트리 등록
│   └── hooks.py         # coreouto 훅 → StreamEvent / EventLog / summarizer
└── providers/
    ├── __init__.py      # ProviderBackend ABC, LLMResponse, get_backend()
    ├── openai.py        # OpenAI Chat Completions 구현 (스트리밍, 안전한 JSON 파싱 포함)
    ├── openai_responses.py  # OpenAI Responses API 구현 (네이티브 스트리밍 포함)
    ├── anthropic.py     # Anthropic 구현 (네이티브 스트리밍, auto max_tokens 포함)
    └── google.py        # Google Gemini 구현
```

---

## 2. 공개 API

`agentouto/__init__.py`에서 엑스포트되는 공개 API:

| 이름 | 타입 | 설명 |
|------|------|------|
| `Agent` | dataclass | 에이전트 설정 |
| `Tool` | class | 도구 데코레이터/클래스 |
| `Provider` | dataclass | 프로바이더 (API 접속 정보) |
| `Message` | dataclass | 전달/반환 메시지 |
| `RunResult` | dataclass | 실행 결과 컨테이너 (output, messages, trace, event_log, token_usage) |
| `run()` | function | 동기 실행 진입점 |
| `async_run()` | async function | 비동기 실행 진입점 |
| `async_run_stream()` | async generator | 스트리밍 실행 진입점 (StreamEvent 생성) |
| `run_background()` | async function | 백그라운드 에이전트 스폰 (async) |
| `run_background_sync()` | function | 백그라운드 에이전트 스폰 (sync) |
| `send_message()` | function | 실행 중인 에이전트에 메시지 주입 |
| `get_agent_status()` | function | 에이전트 상태/메시지 조회 |
| `get_stream_events()` | async generator | 백그라운드 에이전트 스트리밍 이벤트 |
| `AgentLoopRegistry` | class | 스레드 세이프 싱글톤, 모든 루프 추적 |
| `BackgroundAgentLoop` | class | 백그라운드 에이전트 실행 래퍼 |
| `BackgroundResult` | dataclass | 백그라운드 태스크 결과 컨테이너 |
| `RegisteredAgentLoop` | class | 일반/백그라운드 공용 루프 래퍼 |
| `MessageQueue` | class | 에이전트 간 비동기 메시지 큐 |
| `EventLog` | class | 구조화된 이벤트 로그 컨테이너 |
| `AgentEvent` | dataclass | 개별 이벤트 레코드 |
| `Trace` | class | 호출 트리 빌더 |
| `Span` | dataclass | 트레이스 트리의 노드 |
| `StreamEvent` | dataclass | 스트리밍 이벤트 |
| `Attachment` | dataclass | 파일 첨부 데이터 (이미지, 오디오 등) |
| `ToolResult` | dataclass | 도구 리치 반환 타입 (텍스트 + 첨부파일) |
| `Usage` | dataclass | LLM API 토큰 사용량 (input_tokens, output_tokens, total_tokens) |
| `BUILTIN_TOOL_NAMES` | frozenset | 기본 도구 이름 집합 (call_agent, spawn_background_agent, send_message, get_messages, finish) |
| `AuthMethod` | ABC | 인증 방식 추상 클래스 (API 키, OAuth 등) |
| `ApiKeyAuth` | class | 정적 API 키 인증 (하위 호환 래퍼) |
| `OpenAIOAuth` | class | OpenAI OAuth 2.0 + PKCE 인증 |
| `ClaudeOAuth` | class | Anthropic Claude OAuth 인증 (⚠️ TOS 제한) |
| `GoogleOAuth` | class | Google Gemini/Antigravity OAuth 인증 (⚠️ TOS 제한) |
| `TokenData` | dataclass | OAuth 토큰 데이터 컨테이너 |
| `TokenStore` | class | 토큰 영속 저장소 (~/.agentouto/tokens/) |
| `AuthError` | exception | 인증 실패 예외 (OAuth 토큰 갱신 실패 등) |

---

## 3. 모듈별 책임

### `agent.py` — Agent

```python
@dataclass
class Agent:
    name: str               # 에이전트 이름 (필수)
    instructions: str       # 상세 지침 (필수, 에이전트의 시스템 프롬프트에 포함)
    model: str              # 모델 이름 (필수)
    provider: str           # 프로바이더 이름 (필수)
    role: str | None = None # 짧은 역할 설명 (선택, 에이전트 목록에 표시. 없으면 instructions 사용)
    max_output_tokens: int | None  # 최대 출력 토큰 (기본: None → 자동 최대값)
    reasoning: bool         # 추론 모드 토글 (기본: False)
    reasoning_effort: str   # 추론 강도 (기본: "medium")
    reasoning_budget: int | None  # 추론 토큰 예산 (기본: None)
    temperature: float      # 온도 (기본: 1.0)
    context_window: int | None  # 컨텍스트 윈도우 토큰 수 (기본: None → 자동 해결)
    extra: dict[str, Any]   # 추가 파라미터 (기본: {})
```

순수 데이터 컨테이너. 로직 없음. `provider` 필드는 `Provider.name`과 매칭되는 문자열.

`context_window`가 `None`이면 OpenRouter에서 모델 정보를 자동으로 가져와 사용한다. 값을 직접 설정할 수도 있다. 요약은 추정 토큰이 `context_window * 0.70`을 초과할 때마다 에이전트가 스스로 대화를 요약하여 교체한다.

`max_output_tokens`가 `None`이면 각 프로바이더가 자동으로 최대값을 사용한다:
- **OpenAI/Google**: 파라미터 생략 → API가 모델 최대값 자동 적용
- **Anthropic**: `max_tokens` 필수이므로 probe trick 사용 (상세: `PROVIDER_BACKENDS.md`)

### `provider.py` — Provider

```python
@dataclass
class Provider:
    name: str                                    # 식별 이름
    kind: Literal["openai", "openai_responses", "anthropic", "google"]  # API 종류
    api_key: str = ""                            # API 키 (auth 설정 시 생략 가능)
    base_url: str | None = None                  # 커스텀 엔드포인트 (선택)
    auth: AuthMethod | None = None               # OAuth 인증 방식 (선택)

    async def resolve_api_key(self) -> str        # auth 또는 api_key에서 키/토큰 반환
```

API 접속 정보만 담당. 모델 설정은 Agent에서 한다.

`auth`가 설정되면 `resolve_api_key()`는 `auth.get_token()`을 호출하여 OAuth 토큰을 반환한다. `auth`가 `None`이면 기존 `api_key`를 반환한다. 하위 호환성 100% 보장.

### `model_metadata.py` — Model Metadata

모델별 메타데이터 (context_window, max_output_tokens) 관리 모듈.

```python
@dataclass
class ModelMetadata:
    context_window: int
    max_output_tokens: int | None = None

class ModelMetadataError(Exception): ...

async def get_model_info(model: str) -> ModelMetadata
async def resolve_max_output_tokens(model: str, user_value: int | None) -> int | None
async def ensure_loaded() -> None
async def get_context_window(model: str) -> int
def clear_cache() -> None
```

**메타데이터 소스**: LCW API (`https://lcw-api.blp.sh`) 사용

**캐싱**:
- 모델별로 개별적으로 메모리에 캐시됨
- `clear_cache()`로 캐시 초기화 가능
- 모델 이름 정규화: `gpt-4o`, `GPT-4O`, `gpt_4o`, `gpt 4o`는同一 캐시 키로 매핑

**동작 방식**:
- 요청 시 개별 모델-fetch ( lazily, on-demand)
- 첫 번째 조회 시 API에서 메타데이터를 가져와 캐시
- 이후 조회는 캐시에서 즉시 반환
- 모델을 찾지 못하면 `ModelMetadataError` 예외 발생
- `max_output_tokens`는 API의 `maxOutputTokens` 필드에서 제공 (`None`일 수 있음)

### `message.py` — Message

```python
@dataclass
class Message:
    type: Literal["forward", "return"]
    sender: str
    receiver: str
    content: str
    call_id: str  # uuid4 자동 생성
    attachments: list[Attachment] | None = None  # 멀티모달 첨부파일 (선택)
```

런타임이 매 에이전트 호출/반환 시점에 Message 객체를 생성하여 `RunResult.messages`에 수집한다.

### `tool.py` — Tool

`Tool`은 데코레이터로 사용된다:

```python
@Tool
def my_func(arg: str) -> str:
    """설명."""
    return result
```

```python
@dataclass
class ToolResult:
    content: str                              # 텍스트 결과
    attachments: list[Attachment] | None = None  # 첨부파일 (이미지 등)
```

`ToolResult`는 도구가 텍스트와 함께 첨부파일을 반환할 때 사용한다. 기존 `str` 반환도 하위 호환된다.

내부 동작:
1. `func.__name__` → `self.name`
2. `func.__doc__` → `self.description`
3. `inspect.signature` + `get_type_hints(func, include_extras=True)` → JSON Schema 자동 생성
4. `execute(**kwargs)` → 함수 실행 (async 지원), `str | ToolResult` 반환
5. `to_schema()` → LLM에 제공할 도구 스키마 반환

**파라미터 스키마 생성 (`_build_parameters_schema`):**
- 기본 타입 매핑: `_PYTHON_TYPE_TO_JSON` 딕셔너리로 Python 타입 → JSON Schema 타입 변환
- `Annotated[T, "설명"]` → `{"type": ..., "description": "설명"}` (파라미터 설명)
- `Literal["a", "b"]` → `{"type": "string", "enum": ["a", "b"]}` (허용 값 제한)
- `enum.Enum` 서브클래스 → `{"type": ..., "enum": [값들]}` (열거형)
- 기본값 있는 파라미터 → `{"default": 값}` 추가, `required`에서 제외
- 조합 가능: `Annotated[Literal["ko", "en"], "언어"] = "ko"` → description + enum + default 모두 포함

### `context.py` — Context

에이전트별 대화 컨텍스트를 관리하는 프로바이더 비의존적 중간 표현.

```python
@dataclass
class Attachment:
    mime_type: str                # "image/png", "audio/mp3" 등
    data: str | None = None      # base64 인코딩된 데이터
    url: str | None = None       # URL 참조 (data와 상호 배타)
    name: str | None = None      # 선택적 파일명

class Context:
    system_prompt: str              # 시스템 프롬프트 (읽기 전용)
    messages: list[ContextMessage]  # 대화 이력

    def add_user(content, attachments=None)                    # 유저 메시지 추가 (첨부파일 선택)
    def add_assistant_text(content)                            # 어시스턴트 텍스트 추가
    def add_assistant_tool_calls(tool_calls, content)          # 어시스턴트 도구 호출 추가
    def add_tool_result(tool_call_id, tool_name, content, attachments=None)  # 도구 결과 추가 (첨부파일 선택)
    def replace_with_summary(summary, keep_from)               # 오래된 메시지를 요약으로 교체
```

`Attachment` dataclass: `mime_type`, `data`, `url`, `name` 보유. `data` 또는 `url` 중 하나 이상 필수.
`ToolCall` dataclass: `id`, `name`, `arguments` 보유.
`ContextMessage` dataclass: `role`, `content`, `tool_calls`, `tool_call_id`, `tool_name`, `attachments` 보유.

**추론 태그 처리:**

assistant 메시지의 원본 content는 추론 태그(`<think>`, `<thinking>`, `<reason>`, `<reasoning>`)를 포함하여 **그대로 보존**한다. 추론 내용 제거는 context 저장 단계에서 하지 않는다.

추론 태그 내부의 도구 호출 감지 방지는 프로바이더 레벨(`providers/__init__.py`)에서 처리한다:
- `_content_outside_reasoning(content)`: 추론 태그 내용을 제외한 텍스트만 반환
- `LLMResponse.content_without_reasoning`: 추론 태그 제외 content 속성
- 텍스트 기반 파싱 프로바이더는 도구 호출 파싱 전에 `_content_outside_reasoning()`을 사용하여 추론 블록을 제외해야 함
- 구조화된 API 프로바이더(OpenAI, Anthropic, Google)는 도구 호출이 별도 데이터로 반환되므로 이 필터가 불필요

`replace_with_summary(summary, keep_from)`: `_messages[:keep_from]`을 요약 텍스트로 교체한다. `keep_from` 이후 메시지가 user로 시작하면 요약을 해당 메시지에 병합하여 역할 교대 규칙을 유지한다. 그렇지 않으면 요약을 담은 새 user 메시지를 앞에 추가한다.

각 프로바이더 백엔드가 이 Context를 자신의 API 포맷으로 변환한다.

### `summarizer.py` — Context Summarizer

대화가 길어질 때 오래된 메시지를 LLM으로 요약하여 토큰을 절약하고 컨텍스트 오버플로우를 방지하는 모듈. 요약 시 다음 작업 계획(next_steps)도 함께 생성하여 에이전트가 요약 후에도 계속해서 작업을 이어갈 수 있도록 지원한다.

```python
def needs_summarization(context, context_window) -> bool       # 요약 필요 여부 판단 (70% 임계값)
def build_self_summarize_context(messages_to_summarize, system_prompt) -> Context  # 에이전트 자가 요약용 Context 생성
def build_summary_prompt(messages) -> str                       # 메시지를 요약 프롬프트로 포맷
class SummaryResult:
    summary: str
    next_steps: str | None
def parse_summary_response(content: str) -> SummaryResult       # 요약 응답 파싱 (요약 + 다음 단계)
class SummarizeInfo:
    agent_name: str
    messages_to_summarize: list[ContextMessage]
    summary: str
    next_steps: str | None
    tokens_before: int
    tokens_after: int
```

**토큰 추정 (하이브리드 방식):**

Runtime은 `_estimate_current_tokens()`로 현재 컨텍스트 크기를 추정한다:
1. **API 응답 토큰 우선**: `_last_input_tokens` (마지막 API 호출의 실제 input_tokens)가 있으면 사용
2. **증가분 추정**: 이후 추가된 메시지만 `_estimate_message_tokens()`로 추정하여 합산
3. **폴백**: 첫 호출 시 `_last_input_tokens=None`이면 기존 `estimate_context_tokens()` (`len÷4`) 사용

이는 순수 추정(`len÷4`)보다 정확하며, API가 반환한 실제 토큰 수를 기반으로 한다.

**자가 요약 (`build_self_summarize_context`)**: 에이전트가 스스로 대화를 요약하는 방식. 70% 임계값 초과 시:
1. 요약할 메시지를 포맷하여 프롬프트 생성
2. 프롬프트에 `<summary>`와 `<next_steps>` 태그 형식 지시 포함
3. 에이전트의 원본 system_prompt를 유지한 상태에서 요약 요청
4. 에이전트가 생성한 요약과 다음 단계를 `parse_summary_response`로 파싱
5. `on_summarize` 콜백이 등록되어 있으면 호출 — 반환값으로 summary 대체 가능
6. 요약으로 이전 메시지 대체, `next_steps`가 있으면 컨텍스트에 시스템 메시지로 추가
7. 외부 LLM 호출 없이 에이전트 자신이 요약하므로 효율적

**사용자 후킹 (`on_summarize`)**:
```python
from agentouto import SummarizeInfo

def on_summarize(info: SummarizeInfo) -> str | None:
    # info: agent_name, messages_to_summarize, summary, next_steps, tokens_before, tokens_after
    # 반환값이 str이면 해당 문자열로 summary를 대체
    # 반환값이 None이면 기존 summary를 그대로 사용
    print(f"[{info.agent_name}] Summarized {len(info.messages_to_summarize)} messages")
    return None

result = run(..., on_summarize=on_summarize)
```

- 콜백은 `SummarizeInfo` dataclass를 인자로 받음
- 반환값이 `str`이면 해당 문자열로 요약을 대체 (외부 저장소에서 가져오거나, 자체 요약 로직 적용 등)
- 반환값이 `None`이면 기존 요약을 그대로 사용
- 콜백에서 예외가 발생하면 에러를 로깅하고 기존 요약을 그대로 사용 (에러 내성)

**경계 탐색 (`find_summarization_boundary`)**:
1. 메시지 끝에서부터 역순으로 토큰을 누적하며 보존할 메시지 범위 결정
2. `context_window * 0.3` 만큼의 토큰 예산을 최근 메시지에 할당
3. 분할 지점이 `tool` 메시지에 위치하면 뒤로 이동하여 assistant(tool_calls) + tool 결과 쌍을 분리하지 않음
4. 최소 2개 메시지를 보존, 유효한 분할점이 없으면 `None` 반환

**에이전트별 독립 동작**: 각 `_run_agent_loop` 호출이 독립적인 Context를 가지므로 요약도 에이전트별로 독립적으로 동작한다.

### `router.py` — Router

중앙 라우팅 허브. 에이전트, 도구, 프로바이더를 이름으로 관리하고, LLM 호출을 중개한다.

```python
class Router:
    def __init__(agents, tools, providers, *, run_agents=None, disabled_tools=None, allow_background_agents=False)
    def get_agent(name) -> Agent
    def get_tool(name) -> Tool
    def get_builtin_override(name) -> Tool | None
    def build_tool_schemas(current_agent) -> list[dict]  # call_agent + finish 포함 (background 도구는 allow_background_agents=True일 때만)
    def build_system_prompt(agent, caller=None, extra_instructions=None, caller_loop_id=None) -> str
    def call_llm(agent, context, tool_schemas) -> LLMResponse
```

**시스템 프롬프트 자동 생성:**
- 에이전트 이름과 역할/지침 포함
- `role`이 있으면 역할로 사용, 없으면 `instructions` 사용 (하위 호환)
- `role`이 있으면 별도 INSTRUCTIONS 섹션에 상세 지침 포함
- 다른 에이전트 목록 포함 (현재 에이전트 제외, 역할만 표시)
- `call_agent`/`finish` 사용 안내 포함
- `allow_background_agents=True`일 때만 BACKGROUND EXECUTION 섹션 포함
- `extra_instructions` 파라미터가 있으면 "ADDITIONAL INSTRUCTIONS" 섹션으로 시스템 프롬프트에 주입
- `caller_loop_id`가 있으면 INVOKED BY 섹션에 caller의 task_id 안내 포함 (에이전트가 `send_message`로 중간 메시지 전송 가능)

**도구 스키마 자동 생성:**
- 사용자 정의 도구 스키마 전체 (비활성화된 도구 제외)
- 기본 도구 오버라이드: 사용자 도구 이름이 기본 도구와 동일하면 해당 스키마로 교체
- 비활성화: `disabled_tools`에 포함된 기본 도구는 스키마에서 제외 (오버라이드된 경우 제외 안 됨)
- `call_agent` 도구 (agent_name, message 파라미터; `allow_background_agents=True`일 때만 background 파라미터 추가)
- `spawn_background_agent` 도구 (`allow_background_agents=True`일 때만 노출)
- `send_message` 도구 (task_id, message 파라미터) → 전송 확인 반환
- `get_messages` 도구 (task_id, clear 파라미터) → status + messages 반환
- `finish` 도구 (message 파라미터) — 비활성화 불가, 오버라이드 가능

**프로바이더 백엔드 캐싱:**
- `_backends` 딕셔너리로 kind별 백엔드 인스턴스 캐싱
- `get_backend(kind)` 팩토리로 lazy 생성

### `loop_manager.py` — Background Agent Loop Manager

```python
class AgentLoopRegistry:      # Thread-safe singleton for tracking all background loops
class MessageQueue:           # Per-agent async message queue (max 100 messages)
class BackgroundAgentLoop:    # Wrapper for background agent execution
class BackgroundResult:       # Dataclass for background task results
class RegisteredAgentLoop:    # Lightweight wrapper for any running agent loop (normal or background)
                              # Supports: caller_loop_id, on_message callback
```

**AgentLoopRegistry** — Global singleton that tracks all running background agent loops:

```python
registry = AgentLoopRegistry.get_instance()  # Get singleton
registry.register(task_id, bg_loop)          # Register a background loop
registry.unregister(task_id)                 # Remove a loop
registry.get_loop(task_id) -> BackgroundAgentLoop | None
registry.get_task_ids() -> list[str]
```

**MessageQueue** — Async queue for inter-agent messages:

```python
queue: MessageQueue
await queue.enqueue(message)   # Add message (drops oldest if full)
await queue.dequeue(timeout)   # Blocking get (None if timeout)
await queue.peek()             # View without consuming
await queue.clear()            # Empty the queue
```

**BackgroundAgentLoop** — Wrapper for background execution:

```python
bg_loop: BackgroundAgentLoop
bg_loop.start()                        # Begin execution
bg_loop.inject_message(message)        # Inject message into running loop
bg_loop.get_status() -> LoopStatus     # "pending" | "running" | "completed" | "failed"
await bg_loop.get_result() -> str      # Blocking get result
bg_loop.get_messages(clear=False)      # Get all messages
```

**Background execution flow (how agents are spawned):**
1. Router exposes `spawn_background_agent` (or `call_agent(background=True)`) in `build_tool_schemas()` only when `allow_background_agents=True`.
2. Runtime rejects background agent calls with an error message when `allow_background_agents=False`.
3. When enabled, Runtime creates a `BackgroundAgentLoop` for the target agent call and registers it in `AgentLoopRegistry` with a generated `task_id`.
4. `bg_loop.start()` runs the agent loop asynchronously while the caller continues immediately with `task_id`.
5. Other agents can send messages to the running task via `send_message(task_id, message)`; messages are buffered in per-task `MessageQueue`.
6. Callers poll `get_messages(task_id, clear=...)` for status/message snapshots and can await final output via `BackgroundAgentLoop.get_result()`.

**Public API for background execution:**
```python
# Spawn a background agent (async) — requires allow_background_agents=True
task_id = await run_background(
    message="...",
    starting_agents=[...],
    tools=[...],
    providers=[...],
    allow_background_agents=True,
)

# Spawn a background agent (sync) — requires allow_background_agents=True
task_id = run_background_sync(
    message="...",
    starting_agents=[...],
    tools=[...],
    providers=[...],
    allow_background_agents=True,
)

# Send message to a running agent
send_message(task_id, "additional instructions")

# Get status and messages from a running agent
status = get_agent_status(task_id)

# Stream events from a background agent
async for event in get_stream_events(task_id):
    if event["type"] == "token":
        print(event["data"]["text"], end="", flush=True)
    elif event["type"] == "finish":
        print(f"\n--- Result: {event['data']['output']} ---")
```

### `runtime.py` — Runtime

에이전트 루프 엔진. 핵심 모듈.

```python
class Runtime:
    def __init__(router, debug=False, extra_instructions=None, extra_instructions_scope="entry", on_message=None, allow_background_agents=False, on_summarize=None)
    async def execute(agent, forward_message, *, attachments=None, history=None) -> RunResult
    async def _execute_single(agent, forward_message, attachments, history) -> RunResult  # 유저 루프 등록/해제
    async def _run_agent_loop(agent, forward_message, call_id, parent_call_id, *, attachments=None, history=None, extra_instructions=None, caller_loop_id=None) -> str
    async def _execute_tool_call(tc, caller_name, caller_call_id, *, current_loop_id=None) -> str | ToolResult
    async def execute_stream(agent, forward_message, *, attachments=None, history=None) -> AsyncIterator[StreamEvent]
    def _accumulate_usage(response: LLMResponse) -> None  # LLM 응답의 토큰 사용량 누적
    def _estimate_current_tokens(context: Context) -> int  # 하이브리드 토큰 추정
```

**디버그 모드:**
- `debug=True` 시 `EventLog` 인스턴스를 생성하여 모든 이벤트를 기록
- 실행 종료 시 `Trace` 빌드 후 `RunResult`에 포함
- Python `logging` 모듈로 `agentouto` 로거에 디버그 로그 출력
- `debug=False`일 때는 이벤트 기록을 건너뜀 (성능 영향 없음)

**메시지 추적:**
- 매 에이전트 호출/반환 시점에 `Message` 객체를 생성하여 `self._messages`에 수집
- `debug=False`여도 메시지는 항상 수집됨

**토큰 사용량 추적:**
- `_token_usage: Usage` — 모든 LLM 호출의 토큰 사용량 누적
- `_last_input_tokens: int | None` — 마지막 API 호출의 실제 input_tokens (하이브리드 추정용)
- `_last_message_count: int` — 마지막 LLM 호출 시점의 메시지 수
- `_accumulate_usage(response)` — `LLMResponse.usage`가 있으면 `_token_usage`에 합산
- `_estimate_current_tokens(context)` — 실제 토큰 + 새 메시지 추정으로 정확한 컨텍스트 크기 계산

**에이전트 루프 (`_run_agent_loop`):**
`_run_agent_loop`은 얇은 오케스트레이션만 담당한다. 턴 루프 자체는 `coreouto.Agent.call()`가 실행한다.

1. 시스템 프롬프트 생성 → `RunState` 조립 (forward_message, call_id, history, 첨부파일, event_queue 등)
2. `Router.build_tool_schemas()`로 도구 스키마 생성 → coreouto 도구 레지스트리에 디스패치 도구 등록
3. `RunState`를 `_RUN_STATE` ContextVar에 바인딩
4. `coreouto.Agent(config).call(history=...)` 호출 → 최종 응답 문자열 반환
5. ContextVar 언바인딩 (`finally`)

**도구 실행 (`_execute_tool_call`):**
- `call_agent` → `_bridge/tools.py`의 `resolve_agent_target()`으로 대상 검증 후 `_run_agent_loop` 재귀 호출 (sub_call_id 생성, Message 추적)
- 일반 도구 → `resolve_tool_target()`으로 도구 검증 후 `tool.execute(**kwargs)` 실행 → `str | ToolResult` 반환, 에러 시 `ToolError` 래핑
- `ToolResult` 반환 시 `content`와 `attachments`를 분리하여 coreouto `ToolResult`로 변환

**에이전트/도구 혼동 감지 (`_bridge/tools.py`의 `resolve_agent_target` / `resolve_tool_target`):**
- LLM이 도구 이름을 에이전트로 호출 시 → 도구임을 알려주는 에러 메시지 반환
- LLM이 에이전트 이름을 도구로 호출 시 → `call_agent` 사용을 안내하는 에러 메시지 반환
- 존재하지 않는 이름 호출 시 → 사용 가능한 에이전트/도구 목록 포함 에러 메시지 반환
- 에러는 크래시 대신 도구 결과로 LLM에 전달되어 자기 수정 가능

**스트리밍 (`execute_stream`):**
스트리밍은 별도 루프가 아니다. 동일한 `run_agent_loop`을 스트림 콜백이 붙은 상태로 실행한다.

- `RunState.stream=True`로 바인딩하면 `_bridge.provider.DispatchProvider`가 `router.stream_llm()`을 사용하고, 텍스트 청크를 coreouto의 `ON_STREAM_TEXT` 훅 → `StreamEvent(type="token")` 경로로 흘려보낸다
- `tool_call`, `tool_result`, `agent_call`, `agent_return`, `finish`, `error` 이벤트도 `_bridge/hooks.py`의 훅에서 생성된다
- 내부 에이전트 호출은 재귀적으로 sub-stream 생성
- 도구/에이전트 해석 및 실행 에러는 `execute_dispatch`에서 도구 결과 문자열로 전환 (크래시 방지)

**`run()` / `async_run()`:**
- Router 생성 → Runtime 생성 → execute 호출 → RunResult 반환
- `run()`은 `asyncio.run(async_run(...))` 래퍼
- `starting_agents` 파라미터 — 실행할 에이전트 리스트 (`starting_agents[0]`이 entry, 나머지가 병렬 시작)
- `run_agents` 파라미터 — 가시성 스코프 (선택적, 기본값은 `starting_agents`)
- `attachments` 파라미터는 keyword-only (`*, attachments: list[Attachment] | None = None`)
- `history` 파라미터는 keyword-only (`*, history: list[Message] | None = None`) — 이전 대화 이력을 전달
- `debug` 파라미터는 keyword-only (`*, debug: bool = False`)
- `extra_instructions` 파라미터는 keyword-only — 실행 시 에이전트에 전달할 추가 지시 (시스템 프롬프트에 "ADDITIONAL INSTRUCTIONS"로 주입)
- `extra_instructions_scope` 파라미터는 keyword-only (`"entry"` | `"all"`) — `"entry"`면 진입 에이전트에만, `"all"`이면 call_agent로 호출되는 모든 하위 에이전트에도 주입
- `allow_background_agents` 파라미터는 keyword-only (`*, allow_background_agents: bool = False`) — `True`일 때만 `spawn_background_agent`와 `call_agent(background=True)`가 노출됨

**대화 이력 (history):**
- `history` 파라미터로 이전 `RunResult.messages`를 전달하면 에이전트가 이전 대화를 참고할 수 있음
- `call_agent` 도구 호출 시에도 `history` 파라미터를 통해 이전 대화 전달 가능
- 역사는 에이전트의 컨텍스트 앞에 추가되어 현재 메시지보다 먼저 처리됨

**`RunResult`:**
```python
@dataclass
class RunResult:
    output: str                          # 에이전트의 반환 메시지
    messages: list[Message]              # 모든 전달/반환 메시지 (항상 수집)
    trace: Trace | None                  # 호출 트리 (debug=True일 때만)
    event_log: EventLog | None           # 이벤트 로그 (debug=True일 때만)
    token_usage: Usage                   # 누적 API 토큰 사용량

    def format_trace() -> str            # trace.print_tree() 편의 메서드
```

**`token_usage`**: 모든 LLM 호출의 토큰 사용량이 누적된다. `input_tokens`는 프롬프트 토큰, `output_tokens`는 응답 토큰. 요약 LLM 호출의 토큰도 포함된다.

### `_constants.py`

```python
CALL_AGENT = "call_agent"
FINISH = "finish"
```

매직 스트링 방지용. `router.py`와 `runtime.py`에서 공유.

### `_bridge/` — coreouto 어댑터

`coreouto==0.11.3`이 에이전트 턴 루프 엔진이다. `agentouto/_bridge/`는 **coreouto를 import하는 유일한 패키지**다 (다른 모듈은 `runtime.py`가 `run_agent_loop`를 호출할 뿐). 공개 API는 그대로 agentouto 것만 노출한다.

| 모듈 | 책임 |
|------|------|
| `__init__.py` | `run_agent_loop(state)` — `coreouto.Agent(config).call()` 호출. builtin 도구/훅 등록 부트스트랩 |
| `convert.py` | 타입 변환: `Context` ↔ coreouto `Message`, `Attachment` ↔ coreouto `ContentBlock`, agentouto `LLMResponse` ↔ coreouto `LLMResponse`, `Usage` ↔ coreouto `Usage`, `ToolResult` ↔ coreouto `ToolResult` |
| `state.py` | `RunState` 데이터클래스 + `_RUN_STATE` ContextVar |
| `provider.py` | `DispatchProvider` — coreouto `Provider` 프로토콜 구현 |
| `tools.py` | builtin + 사용자 도구 디스패치, coreouto 도구 레지스트리 등록 |
| `hooks.py` | coreouto 훅 → `StreamEvent` / `EventLog` / summarizer |

**왜 ContextVar인가 (`state.py`):** coreouto의 도구/훅/프로바이더 레지스트리는 프로세스 전역이다. 그래서 실행 단위 상태를 인스턴스로 들고 다닐 수 없고, 모든 디스패치 진입점(도구 핸들러, 훅, provider shim)이 `_RUN_STATE` ContextVar로 현재 실행을 조회한다. `asyncio`는 컨텍스트를 `asyncio.gather` 자식, 중첩 에이전트 루프, `asyncio.to_thread`까지 전파하므로 컨텍스트 전파가 그대로 재사용된다. `require_run_state()`가 컨텍스트가 없으면 명시적으로 실패한다.

**`provider.py` — `DispatchProvider`:**
- agentouto의 프로바이더 백엔드가 와이어 포맷을 소유한다 (멀티모달 도구 결과, JSON 인자 복구). coreouto의 기본 프로바이더는 멀티모달 도구 결과와 JSON 인자 복구에서 후퇴하므로, 이 shim은 변환만 하고 LLM 호출은 `router.call_llm` / `router.stream_llm`로 중개한다. 덕분에 테스트의 `patch("agentouto.router.get_backend")` 심이 그대로 유지된다.
- `finish` 도구 호출이 있으면 응답을 텍스트 응답으로 정규화한다 (`tool_calls=[]`, `content=resolve_finish_result(...)`). 동시 호출된 형제 도구 호출은 의도적으로 버린다 — 이전 루프도 `finish`를 보자마자 반환했기 때문이다.
- `_stream` 속성을 가진 인스턴스 하나로 동시 실행을 모두 처리한다. 스트림 여부는 `RunState.stream`으로 판단한다.

**`tools.py`:**
- coreouto에는 "이미 만들어진 Tool 등록" API가 없다(데코레이터 형태만 있고 `Any` 파라미터를 거부한다). agentouto 디스패치 핸들러는 임의 인자를 받고 스키마는 `Router.build_tool_schemas`가 제공하므로, 고정된 0.11.x 레지스트리 dict에 직접 등록한다.
- 에이전트 이름도 도구로 등록한다 — 에이전트를 도구로 부르는 것은 라우팅 가능한 실수이며, agentouto 자체의 에러 메시지를 내야 하기 때문이다.
- `execute_dispatch()`는 절대 raise하지 않고 항상 텍스트를 반환한다. 이렇게 해야 coreouto의 예외 삼킴이 개입하지 않아 agentouto의 정확한 에러 문자열이 모델까지 전달된다 (에러 → 도구 결과 원칙 유지).

**`hooks.py`:**
- `BEFORE_LLM_CALL` — 주입 메시지 반영(`send_message`, `on_message`) + 자가 요약 + `llm_call` 이벤트 기록
- `AFTER_LLM_CALL` — `llm_response` 이벤트 기록, 토큰 사용량 누적, 하이브리드 추정용 `_last_input_tokens` 갱신
- `BEFORE_TOOL_CALL` / `AFTER_TOOL_CALL` — `tool_call` / `tool_result` 스트림 이벤트. 레지스트리에 없는 도구 이름은 coreouto의 `"tool not found: X"`를 agentouto 문구로 재작성한다.
- `ON_FINISH` — `finish` 스트림 이벤트 + 이벤트 로그 기록
- `ON_STREAM_TEXT` → `token` 이벤트, `ON_STREAM_THINKING` → 버림 (agentouto에 thinking 이벤트가 없음)
- 훅 레지스트리도 전역이므로 프로세스당 1회만 등록하고, 각 훅은 agentouto가 호출자가 아닐 때 no-op 한다.

**단일 루프 설계:** 이전에는 `_run_agent_loop`와 `_stream_agent_loop`이 같은 로직을 중복 구현했다(스트리밍 쪽만 `stream_llm`을 쓰고 종료 처리를 따로 반복). 이제 루프는 하나뿐이고, 스트리밍은 같은 루프에 스트림 콜백이 붙은 상태다.

**에이전트 백엔드를 여전히 유지하는 이유:** coreouto가 제공하는 stock provider 대신 agentouto의 백엔드를 `DispatchProvider`로 중개한다. 멀티모달 도구 결과 전달과 손상된 JSON 인자 복구에서 자체 백엔드가 더 정확하기 때문이다. 종료 판단에 필요한 벤더 종료 사유는 `LLMResponse.stop_reason`으로 전달된다.

### `exceptions.py`

```
AgentOutOError (base)
├── ProviderError(provider_name, message)
├── AgentError(agent_name, message)
├── ToolError(tool_name, message)
├── RoutingError(message)
└── AuthError(provider_name, message)
```

### `event_log.py` — EventLog

구조화된 이벤트 로깅 시스템.

```python
EventType = Literal["llm_call", "llm_response", "tool_exec", "agent_call", "agent_return", "finish", "error"]

@dataclass
class AgentEvent:
    event_type: EventType
    agent_name: str
    call_id: str
    parent_call_id: str | None
    timestamp: float           # time.time() 자동 생성
    details: dict[str, Any]    # 이벤트별 추가 데이터

class EventLog:
    def record(event)
    def events -> list[AgentEvent]   # 복사본 반환
    def filter(agent_name=None, event_type=None) -> list[AgentEvent]
    def format() -> str              # 사람이 읽을 수 있는 포맷
    def __iter__ / __len__
```

`Runtime._record()` 메서드가 디버그 모드일 때만 이벤트를 기록한다.

### `tracing.py` — Trace

호출 체인 트리 구축.

```python
@dataclass
class Span:
    agent_name: str
    call_id: str
    parent_call_id: str | None
    start_time: float
    end_time: float
    children: list[Span]
    tool_calls: list[dict[str, Any]]
    result: str | None
    duration -> float          # property

class Trace:
    def __init__(event_log: EventLog)   # EventLog에서 트리 자동 구축
    def root -> Span | None
    def print_tree() -> str             # ASCII 트리 시각화
```

`Trace`는 `EventLog`의 `call_id`/`parent_call_id` 관계로 트리를 빌드한다.

### `streaming.py` — Streaming

스트리밍 인터페이스.

```python
@dataclass
class StreamEvent:
    type: Literal["token", "tool_call", "tool_result", "agent_call", "agent_return", "finish", "error"]
    agent_name: str
    call_id: str                          # uuid4 — 에이전트 호출 고유 ID
    parent_call_id: str | None            # 부모 호출 ID (呼叫 체인 추적)
    data: dict[str, Any] = field(default_factory=dict)

async def async_run_stream(entry, message, agents, tools, providers, *, attachments=None) -> AsyncIterator[StreamEvent]
```

`async_run_stream()`은 `Runtime.execute_stream()`을 랩한다.

### `auth/` — 인증 모듈

OAuth 2.0 및 정적 API 키 인증을 추상화하는 모듈.

```python
class AuthMethod(ABC):
    async def get_token(self) -> str              # 유효한 토큰 반환 (만료 시 자동 갱신)
    async def ensure_authenticated(self) -> None  # 인증 플로우 실행 (브라우저 열기 등)
    is_authenticated: bool                        # 현재 인증 상태

@dataclass
class TokenData:
    access_token: str
    refresh_token: str | None
    expires_at: float | None
    scopes: list[str]
    extra: dict[str, Any]
```

**구현체:**
- `ApiKeyAuth` — 정적 API 키 래퍼. 기존 `api_key` 동작과 동일.
- `OpenAIOAuth` — OpenAI OAuth 2.0 + PKCE. ChatGPT Plus/Pro 구독 인증.
- `ClaudeOAuth` — Anthropic Claude OAuth (⚠️ TOS 제한, 기본 client_id 주석 처리).
- `GoogleOAuth` — Google Gemini/Antigravity OAuth (⚠️ TOS 제한, 기본 client_id 주석 처리).

**TokenStore:**
- `~/.agentouto/tokens/` 디렉토리에 토큰 JSON 저장 (파일: `0o600`, 디렉토리: `0o700`)
- `save(provider_name, tokens)` / `load(provider_name)` / `delete(provider_name)`

**_oauth_common.py:**
- `generate_pkce()` — PKCE code_verifier + code_challenge (S256)
- `find_free_port()` — localhost 랜덤 포트
- `wait_for_callback(port, timeout)` — 로컬 HTTP 서버로 OAuth 콜백 수신
- `exchange_token(token_url, params)` — 토큰 교환 (aiohttp 사용, lazy import)
- `refresh_access_token(token_url, refresh_token, client_id)` — 토큰 갱신
- `build_authorize_url(...)` — 인증 URL 생성

### `providers/__init__.py`

```python
@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens -> int  # property: input_tokens + output_tokens

class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall]
    usage: Usage | None                    # API 토큰 사용량 (선택적)
    stop_reason: str | None = None         # 벤더 종료 사유 (상세: PROVIDER_BACKENDS.md)
    content_without_reasoning -> str | None  # property: 추론 태그 제외 content

class ProviderBackend(ABC):
    async def call(context, tools, agent, provider) -> LLMResponse
    async def stream(context, tools, agent, provider) -> AsyncIterator[str | LLMResponse]
        # 기본 구현: call() 호출 후 content + LLMResponse 순서대로 yield (fallback)
        # OpenAI, Anthropic은 네이티브 스트리밍 구현 (str 청크를 실시간 yield)

def get_backend(kind: str) -> ProviderBackend  # 팩토리 함수
```

`get_backend`는 lazy import로 각 백엔드 모듈을 로드한다.

**`Usage` 데이터클래스:**
- `input_tokens`: 프롬프트에 사용된 토큰 수
- `output_tokens`: LLM 응답에 사용된 토큰 수
- `total_tokens` 프로퍼티: `input_tokens + output_tokens`
- `__add__`, `__iadd__` 연산자 지원: 여러 호출의 토큰 합산 가능
- 모든 프로바이더 백엔드가 API 응답에서 추출하여 `LLMResponse.usage`에 포함

**추론 태그 유틸리티:**
- `_content_outside_reasoning(content)` — `<think>`, `<thinking>`, `<reason>`, `<reasoning>` 태그 내용을 제외한 텍스트 반환
- `LLMResponse.content_without_reasoning` 속성 — 위 유틸리티를 사용한 편의 속성
- 텍스트 기반 파싱 프로바이더는 도구 호출 파싱 전에 이 유틸리티로 추론 블록을 제외해야 함

---

## 4. 데이터 흐름

### 실행 시작 → 결과 반환

```
run(message, starting_agents, tools, providers, ...)
  │
  ├── Router(starting_agents, tools, providers)
  ├── Runtime(router)
  └── runtime.execute(entry, starting_agents, ...)
        │
        └── _run_agent_loop(entry, message)
              │
              ├── router.build_system_prompt(agent)   ← 시스템 프롬프트 생성
              ├── RunState 조립 (message, history, attachments, event_queue)
              ├── router.build_tool_schemas(agent.name) ← 도구 스키마 생성
              ├── bind_run_state(state)                 ← ContextVar 바인딩
              │
              └── coreouto.Agent(config).call(history=...)
                    │
                    └── (coreouto 턴 루프)
                          ├── BEFORE_LLM_CALL 훅 → 주입 메시지 반영, 자가 요약
                          ├── DispatchProvider.create()
                          │     ├── Context 재구성 (convert.py)
                          │     ├── router.call_llm / stream_llm
                          │     │     ├── provider = providers[agent.provider]
                          │     │     ├── backend = get_backend(provider.kind)
                          │     │     └── backend.call(context, schemas, agent, provider)
                          │     │           └── LLMResponse(content, tool_calls, usage, stop_reason)
                          │     └── finish 도구 호출 → 텍스트 응답으로 정규화
                          ├── tool_calls 있음 → coreouto 도구 레지스트리 디스패치
                          │     ├── call_agent → _run_agent_loop(target, msg)  [재귀]
                          │     └── tool → tool.execute(**kwargs)
                          └── 루프 종료 → 응답 텍스트 반환
```

### 루프 종료 조건

에이전트 루프는 다음 중 하나에서 종료한다:

1. **텍스트 응답 + 도구 호출 없음** → 해당 텍스트가 최종 답 (coreouto 컨벤션). `finish()`를 강제하지 않는다.
2. **`finish(message=X)` 호출** → `X`가 최종 답. 브릿지의 provider shim이 이를 텍스트 응답으로 정규화하므로 1번과 동일한 경로다.
3. **복구 불가능한 프로바이더 종료** (토큰 상한, refusal, 콘텐츠 필터 등) → 부분 텍스트가 있으면 그것이 결과.
4. **빈 content + 도구 호출 없음** → 아직 작업 중이므로 루프를 계속한다.
5. **스트리밍 백엔드가 최종 `LLMResponse`를 내지 않음** → `NoLLMResponseError` → `StreamEvent(type="error")` 후 빈 문자열 반환.

`max_iterations`는 설정하지 않는다 (`None`) — 철학상 시스템 레벨 반복 제한이 없다.

### 프로바이더 백엔드 데이터 변환

```
Context (프로바이더 비의존)
    │
    ├── OpenAI (Chat Completions):  _build_messages(context) → list[dict]  (role/content/tool_calls)
    ├── OpenAI (Responses):  _build_input(context) → list[dict]  (input items + instructions)
    ├── Anthropic: _build_messages(context) → list[dict]  (content blocks)
    └── Google:  _build_contents(context) → list[Content]  (protos)
```

각 백엔드는 Context의 통일된 표현을 자신의 API 포맷으로 변환한다.

---

## 5. 의존성

### 런타임 의존성

| 패키지 | 버전 | 용도 |
|--------|------|------|
| `coreouto` | ≥0.11.3, <0.12 | 에이전트 턴 루프 엔진. `agentouto/_bridge/`에서만 import |
| `openai` | ≥1.50.0 | OpenAI 및 호환 API 클라이언트 |
| `anthropic` | ≥0.34.0 | Anthropic API 클라이언트 |
| `google-generativeai` | ≥0.8.0 | Google Gemini API 클라이언트 |

`coreouto`는 alpha 단계의 업스트림이므로 버전을 고정(pin)한다. `agentouto/_bridge/`는 coreouto를 감싸는 어댑터일 뿐이며, coreouto의 이름을 재export하지 않는다. 사용자는 계속 `agentouto`에서만 import한다.

### 선택적 의존성 (`[oauth]`)

| 패키지 | 버전 | 용도 |
|--------|------|------|
| `aiohttp` | ≥3.9.0 | OAuth 토큰 교환 HTTP 클라이언트 |

OAuth 기능 설치: `pip install agentouto[oauth]`
`aiohttp`는 lazy import로 로드되므로 OAuth를 사용하지 않으면 설치하지 않아도 된다.

### 개발 의존성

| 패키지 | 버전 | 용도 |
|--------|------|------|
| `pytest` | ≥8.0 | 테스트 |
| `pytest-asyncio` | ≥0.23 | 비동기 테스트 |
| `mypy` | ≥1.8 | 타입 체크 |

### 표준 라이브러리 사용

| 모듈 | 사용 위치 |
|------|----------|
| `asyncio` | `runtime.py` — gather, run |
| `base64` | `providers/google.py` — 첨부파일 바이너리 디코딩 |
| `json` | `providers/openai.py` — tool call 파싱 |
| `uuid` | `message.py`, `providers/google.py`, `runtime.py` — ID 생성 |
| `inspect` | `tool.py` — 함수 시그니처 분석 |
| `typing` | 전역 — 타입 힌팅 |
| `dataclasses` | 데이터 클래스 정의 |
| `abc` | `providers/__init__.py` — 추상 클래스 |
| `logging` | `runtime.py` — 디버그 로그, `providers/openai.py` — 파싱 경고, `providers/anthropic.py` — max_tokens 탐색 로그 |
| `re` | `providers/__init__.py` — 추론 태그 정규식, `providers/anthropic.py` — 에러 메시지 파싱 |
| `time` | `event_log.py` — 타임스탬프 |
| `collections.abc` | `runtime.py`, `streaming.py`, `providers/` — AsyncIterator |

---

## 6. 핵심 설계 패턴

### 패턴 1: 이름 기반 레지스트리

에이전트, 도구, 프로바이더는 모두 이름(문자열)으로 참조된다.
- `Agent.provider = "openai"` → `Router._providers["openai"]`
- LLM이 `call_agent(agent_name="writer")` → `Router._agents["writer"]`
- LLM이 `search_web(...)` → `Router._tools["search_web"]`

### 패턴 2: 재귀적 에이전트 루프

`call_agent`는 `_run_agent_loop`을 재귀적으로 호출한다. 각 호출은 독립적인 Context를 가진다. 호출 스택이 곧 에이전트 호출 체인이다.

### 패턴 3: 프로바이더 추상화

`ProviderBackend` ABC → 각 kind별 구현체. `get_backend(kind)` 팩토리가 lazy import로 인스턴스를 생성한다. Router가 kind별로 캐싱한다.

### 패턴 4: 에러 → 도구 결과

도구 실행 에러를 예외로 전파하지 않고 에러 문자열을 도구 결과로 만들어 LLM에게 전달한다. 런타임이 크래시하지 않고 LLM이 에러를 보고 판단한다. 병렬 도구 실행과 예외 수집은 coreouto 루프가 담당하고, agentouto는 `_bridge/tools.py:execute_dispatch()`에서 예외를 문자열로 바꿔 반환한다.

### 패턴 5: 토큰 로테이션 캐싱

OAuth 토큰이 갱신될 수 있으므로, 프로바이더 백엔드는 `(api_key, client)` 튜플로 클라이언트를 캐싱한다:

```python
class OpenAIBackend:
    def __init__(self) -> None:
        self._clients: dict[str, tuple[str, AsyncOpenAI]] = {}

    def _get_client(self, provider: Provider, api_key: str) -> AsyncOpenAI:
        cached = self._clients.get(provider.name)
        if cached is not None and cached[0] == api_key:
            return cached[1]
        client = AsyncOpenAI(api_key=api_key, base_url=provider.base_url)
        self._clients[provider.name] = (api_key, client)
        return client
```

`call()`/`stream()`에서 `api_key = await provider.resolve_api_key()`를 호출한 후 `_get_client(provider, api_key)`로 전달한다. 토큰이 변경되면 클라이언트를 새로 생성한다.

`asyncio.gather(return_exceptions=True)`로 에러를 도구 결과에 포함시켜 LLM에게 전달한다. 런타임이 크래시하지 않고 LLM이 에러를 보고 판단한다.
