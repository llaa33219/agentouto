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
├── message.py           # Message 데이터클래스
├── provider.py          # Provider 데이터클래스
├── router.py            # 메시지 라우팅, 시스템 프롬프트, 도구 스키마
├── runtime.py           # 에이전트 루프 엔진, 병렬 실행, 스트리밍, run()/async_run()
├── streaming.py         # 스트리밍 인터페이스 (StreamEvent, async_run_stream)
├── tool.py              # Tool 데코레이터/클래스
├── tracing.py           # 호출 트레이싱 (Span, Trace)
└── providers/
    ├── __init__.py      # ProviderBackend ABC, LLMResponse, get_backend()
    ├── openai.py        # OpenAI 구현 (스트리밍, 안전한 JSON 파싱 포함)
    ├── anthropic.py     # Anthropic 구현 (auto max_tokens 탐색 포함)
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
| `RunResult` | dataclass | 실행 결과 컨테이너 (output, messages, trace, event_log) |
| `run()` | function | 동기 실행 진입점 |
| `async_run()` | async function | 비동기 실행 진입점 |
| `async_run_stream()` | async generator | 스트리밍 실행 진입점 (StreamEvent 생성) |
| `EventLog` | class | 구조화된 이벤트 로그 컨테이너 |
| `AgentEvent` | dataclass | 개별 이벤트 레코드 |
| `Trace` | class | 호출 트리 빌더 |
| `Span` | dataclass | 트레이스 트리의 노드 |
| `StreamEvent` | dataclass | 스트리밍 이벤트 |
| `Attachment` | dataclass | 파일 첨부 데이터 (이미지, 오디오 등) |
| `ToolResult` | dataclass | 도구 리치 반환 타입 (텍스트 + 첨부파일) |

---

## 3. 모듈별 책임

### `agent.py` — Agent

```python
@dataclass
class Agent:
    name: str               # 에이전트 이름 (필수)
    instructions: str       # 역할 설명 (필수)
    model: str              # 모델 이름 (필수)
    provider: str           # 프로바이더 이름 (필수)
    max_output_tokens: int | None  # 최대 출력 토큰 (기본: None → 자동 최대값)
    reasoning: bool         # 추론 모드 토글 (기본: False)
    reasoning_effort: str   # 추론 강도 (기본: "medium")
    reasoning_budget: int | None  # 추론 토큰 예산 (기본: None)
    temperature: float      # 온도 (기본: 1.0)
    extra: dict[str, Any]   # 추가 파라미터 (기본: {})
```

순수 데이터 컨테이너. 로직 없음. `provider` 필드는 `Provider.name`과 매칭되는 문자열.

`max_output_tokens`가 `None`이면 각 프로바이더가 자동으로 최대값을 사용한다:
- **OpenAI/Google**: 파라미터 생략 → API가 모델 최대값 자동 적용
- **Anthropic**: `max_tokens` 필수이므로 probe trick 사용 (상세: `PROVIDER_BACKENDS.md`)

### `provider.py` — Provider

```python
@dataclass
class Provider:
    name: str                                    # 식별 이름
    kind: Literal["openai", "anthropic", "google"]  # API 종류
    api_key: str                                 # API 키
    base_url: str | None                         # 커스텀 엔드포인트 (선택)
```

API 접속 정보만 담당. 모델 설정은 Agent에서 한다.

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

각 프로바이더 백엔드가 이 Context를 자신의 API 포맷으로 변환한다.

### `router.py` — Router

중앙 라우팅 허브. 에이전트, 도구, 프로바이더를 이름으로 관리하고, LLM 호출을 중개한다.

```python
class Router:
    def __init__(agents, tools, providers)
    def get_agent(name) -> Agent
    def get_tool(name) -> Tool
    def build_tool_schemas(current_agent) -> list[dict]  # call_agent + finish 포함
    def build_system_prompt(agent) -> str                 # 에이전트 목록 포함
    def call_llm(agent, context, tool_schemas) -> LLMResponse
```

**시스템 프롬프트 자동 생성:**
- 에이전트 이름과 instructions 포함
- 다른 에이전트 목록 포함 (현재 에이전트 제외)
- `call_agent`/`finish` 사용 안내 포함

**도구 스키마 자동 생성:**
- 사용자 정의 도구 스키마 전체
- `call_agent` 도구 (agent_name, message 파라미터)
- `finish` 도구 (message 파라미터)

**프로바이더 백엔드 캐싱:**
- `_backends` 딕셔너리로 kind별 백엔드 인스턴스 캐싱
- `get_backend(kind)` 팩토리로 lazy 생성

### `runtime.py` — Runtime

에이전트 루프 엔진. 핵심 모듈.

```python
class Runtime:
    def __init__(router, debug=False)
    async def execute(agent, forward_message, *, attachments=None) -> RunResult
    async def _run_agent_loop(agent, forward_message, call_id, parent_call_id, *, attachments=None) -> str
    async def _execute_tool_call(tc, caller_name, caller_call_id) -> str | ToolResult
    async def execute_stream(agent, forward_message, *, attachments=None) -> AsyncIterator[StreamEvent]
    async def _stream_agent_loop(agent, forward_message, call_id, parent_call_id, *, attachments=None) -> AsyncIterator[StreamEvent]
```

**디버그 모드:**
- `debug=True` 시 `EventLog` 인스턴스를 생성하여 모든 이벤트를 기록
- 실행 종료 시 `Trace` 빌드 후 `RunResult`에 포함
- Python `logging` 모듈로 `agentouto` 로거에 디버그 로그 출력
- `debug=False`일 때는 이벤트 기록을 건너뜀 (성능 영향 없음)

**메시지 추적:**
- 매 에이전트 호출/반환 시점에 `Message` 객체를 생성하여 `self._messages`에 수집
- `debug=False`여도 메시지는 항상 수집됨

**에이전트 루프 (`_run_agent_loop`):**
1. 시스템 프롬프트 생성 → Context 초기화
2. forward_message를 user 메시지로 추가 (첨부파일이 있으면 함께 추가)
3. 무한 루프:
   a. LLM 호출 (이벤트 기록: `llm_call`, `llm_response`)
   b. tool_calls가 없으면 → 텍스트 응답 반환
   c. `finish` 호출이 있으면 → message 반환 (이벤트 기록: `finish`)
   d. tool_calls를 `asyncio.gather`로 병렬 실행 (이벤트 기록: `tool_exec`, `agent_call`)
   e. 결과를 tool result로 추가 (ToolResult인 경우 첨부파일 포함)
   f. 다음 반복

**도구 실행 (`_execute_tool_call`):**
- `call_agent` → 대상 에이전트의 `_run_agent_loop` 재귀 호출 (sub_call_id 생성, Message 추적)
- 일반 도구 → `tool.execute(**kwargs)` 실행 → `str | ToolResult` 반환, 에러 시 `ToolError` 래핑
- `ToolResult` 반환 시 `content`와 `attachments`를 분리하여 context에 추가

**스트리밍 (`execute_stream` / `_stream_agent_loop`):**
- `Router.stream_llm()`을 통해 LLM 스트리밍 호출
- 텍스트 청크는 `StreamEvent(type="token")`로 즐시 yield
- 도구 호출, 에이전트 호출, 완료도 각각 StreamEvent로 yield
- 내부 에이전트 호출은 재귀적으로 sub-stream 생성

**`run()` / `async_run()`:**
- Router 생성 → Runtime 생성 → execute 호출 → RunResult 반환
- `run()`은 `asyncio.run(async_run(...))` 래퍼
- `attachments` 파라미터는 keyword-only (`*, attachments: list[Attachment] | None = None`)
- `debug` 파라미터는 keyword-only (`*, debug: bool = False`)

**`RunResult`:**
```python
@dataclass
class RunResult:
    output: str                          # 에이전트의 반환 메시지
    messages: list[Message]              # 모든 전달/반환 메시지 (항상 수집)
    trace: Trace | None                  # 호출 트리 (debug=True일 때만)
    event_log: EventLog | None           # 이벤트 로그 (debug=True일 때만)

    def format_trace() -> str            # trace.print_tree() 편의 메서드
```

### `_constants.py`

```python
CALL_AGENT = "call_agent"
FINISH = "finish"
```

매직 스트링 방지용. `router.py`와 `runtime.py`에서 공유.

### `exceptions.py`

```
AgentOutOError (base)
├── ProviderError(provider_name, message)
├── AgentError(agent_name, message)
├── ToolError(tool_name, message)
└── RoutingError(message)
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
    type: Literal["token", "tool_call", "agent_call", "agent_return", "finish", "error"]
    agent_name: str
    data: dict[str, Any]

async def async_run_stream(entry, message, agents, tools, providers, *, attachments=None) -> AsyncIterator[StreamEvent]
```

`async_run_stream()`은 `Runtime.execute_stream()`을 랩한다.

### `providers/__init__.py`

```python
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall]
    content_without_reasoning -> str | None  # property: 추론 태그 제외 content

class ProviderBackend(ABC):
    async def call(context, tools, agent, provider) -> LLMResponse
    async def stream(context, tools, agent, provider) -> AsyncIterator[str | LLMResponse]
        # 기본 구현: call() 호출 후 content + LLMResponse 순서대로 yield (fallback)
        # OpenAI만 네이티브 스트리밍 구현 (str 청크를 실시간 yield)

def get_backend(kind: str) -> ProviderBackend  # 팩토리 함수
```

`get_backend`는 lazy import로 각 백엔드 모듈을 로드한다.

**추론 태그 유틸리티:**
- `_content_outside_reasoning(content)` — `<think>`, `<thinking>`, `<reason>`, `<reasoning>` 태그 내용을 제외한 텍스트 반환
- `LLMResponse.content_without_reasoning` 속성 — 위 유틸리티를 사용한 편의 속성
- 텍스트 기반 파싱 프로바이더는 도구 호출 파싱 전에 이 유틸리티로 추론 블록을 제외해야 함

---

## 4. 데이터 흐름

### 실행 시작 → 결과 반환

```
run(entry, message, agents, tools, providers)
  │
  ├── Router(agents, tools, providers)   ← 이름 기반 레지스트리 생성
  ├── Runtime(router)
  └── runtime.execute(entry, message)
        │
        └── _run_agent_loop(entry, message)
              │
              ├── router.build_system_prompt(agent)  ← 시스템 프롬프트 생성
              ├── Context(system_prompt)              ← 컨텍스트 초기화
              ├── context.add_user(message, attachments)  ← 전달 메시지 + 첨부파일 추가
              ├── router.build_tool_schemas(agent.name) ← 도구 스키마 생성
              │
              └── while True:
                    ├── router.call_llm(agent, context, schemas)
                    │     ├── provider = providers[agent.provider]
                    │     ├── backend = get_backend(provider.kind)
                    │     └── backend.call(context, schemas, agent, provider)
                    │           └── LLMResponse(content, tool_calls)
                    │
                    ├── no tool_calls? → return content
                    ├── finish found? → return finish.message
                    │
                    ├── context.add_assistant_tool_calls(tool_calls)
                    ├── asyncio.gather(*[_execute_tool_call(tc) for tc in tool_calls])
                    │     ├── call_agent → _run_agent_loop(target, msg)  [재귀]
                    │     └── tool → tool.execute(**kwargs)
                    │
                    └── context.add_tool_result(id, name, result_or_error, attachments)
```

### 프로바이더 백엔드 데이터 변환

```
Context (프로바이더 비의존)
    │
    ├── OpenAI:  _build_messages(context) → list[dict]  (role/content/tool_calls)
    ├── Anthropic: _build_messages(context) → list[dict]  (content blocks)
    └── Google:  _build_contents(context) → list[Content]  (protos)
```

각 백엔드는 Context의 통일된 표현을 자신의 API 포맷으로 변환한다.

---

## 5. 의존성

### 런타임 의존성

| 패키지 | 버전 | 용도 |
|--------|------|------|
| `openai` | ≥1.50.0 | OpenAI 및 호환 API 클라이언트 |
| `anthropic` | ≥0.34.0 | Anthropic API 클라이언트 |
| `google-generativeai` | ≥0.8.0 | Google Gemini API 클라이언트 |

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

`asyncio.gather(return_exceptions=True)`로 에러를 도구 결과에 포함시켜 LLM에게 전달한다. 런타임이 크래시하지 않고 LLM이 에러를 보고 판단한다.
