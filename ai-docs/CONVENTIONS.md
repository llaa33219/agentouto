# Conventions — 코딩 컨벤션

이 문서는 프로젝트의 코딩 패턴, 네이밍, 스타일 가이드를 설명한다.

---

## 1. 언어 및 버전

- **Python ≥ 3.11** (3.10 이하 미지원)
- `from __future__ import annotations` 모든 모듈 상단에 포함
- Union 타입은 `X | Y` 신택스 사용 (`Union[X, Y]` 아님)

---

## 2. 타입 힌팅

### 필수

모든 함수 시그니처에 타입 힌팅을 포함한다:

```python
# ✅ Good
async def call(self, context: Context, tools: list[dict[str, Any]], agent: Agent, provider: Provider) -> LLMResponse:

# ❌ Bad
async def call(self, context, tools, agent, provider):
```

### 규칙

- 반환 타입 항상 명시 (`-> None` 포함)
- `Any` 사용 최소화 — 구체적 타입 사용 우선
- `TYPE_CHECKING` 가드로 순환 import 방지:
  ```python
  from typing import TYPE_CHECKING
  if TYPE_CHECKING:
      from agentouto.agent import Agent
  ```

---

## 3. 데이터 클래스

### 순수 데이터에는 `@dataclass` 사용

```python
@dataclass
class Agent:
    name: str
    instructions: str
    ...
```

### 커스텀 `__init__`이 필요하면 일반 클래스

```python
class Tool:  # @dataclass 아님
    def __init__(self, func: Callable[..., Any]) -> None:
        self.name = func.__name__
        ...
```

### 기본값

- 불변 기본값: 직접 지정 (`temperature: float = 1.0`)
- 가변 기본값: `field(default_factory=...)` 사용 (`extra: dict[str, Any] = field(default_factory=dict)`)

---

## 4. 네이밍

| 대상 | 규칙 | 예시 |
|------|------|------|
| 모듈 | snake_case | `runtime.py`, `provider.py` |
| 클래스 | PascalCase | `ProviderBackend`, `RunResult` |
| 함수/메서드 | snake_case | `build_tool_schemas`, `_run_agent_loop` |
| 상수 | UPPER_SNAKE_CASE | `CALL_AGENT`, `FINISH` |
| 프라이빗 | 언더스코어 접두사 | `_clients`, `_build_messages` |
| 모듈 프라이빗 파일 | 언더스코어 접두사 | `_constants.py` |

---

## 5. 비동기 패턴

### 전체 `async/await` 기반

- LLM 호출, 도구 실행, 에이전트 호출 모두 비동기
- 동기 래퍼 (`run()`)는 `asyncio.run(async_run(...))` 사용
- 동기 도구 함수도 `inspect.isawaitable`로 자동 처리

### 병렬 실행

```python
results = await asyncio.gather(*tasks, return_exceptions=True)
```

`return_exceptions=True`를 사용하여 개별 실패가 전체를 중단하지 않게 한다.

---

## 6. 에러 처리

### 예외 계층

```
AgentOutOError
├── ProviderError(provider_name, message)
├── AgentError(agent_name, message)
├── ToolError(tool_name, message)
└── RoutingError(message)
```

### 규칙

- API 호출은 `try/except → ProviderError` 래핑
- 도구 실행은 `try/except → ToolError` 래핑
- **에이전트 루프 내 에러는 도구 결과에 포함** — 크래시 대신 LLM에게 에러를 보여준다
- 불필요한 try/catch 남발하지 않는다

---

## 7. 모듈 구조

### Import 순서

1. `from __future__ import annotations`
2. 표준 라이브러리
3. 서드파티 라이브러리
4. 프로젝트 내부 모듈

```python
from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from agentouto.agent import Agent
from agentouto.context import Context, ToolCall
from agentouto.exceptions import ProviderError
from agentouto.provider import Provider
from agentouto.providers import LLMResponse, ProviderBackend
```

### 모듈 프라이빗 함수

모듈 내에서만 사용되는 헬퍼는 `_` 접두사:

```python
def _build_messages(context: Context) -> list[dict[str, Any]]:  # 모듈 프라이빗
    ...
```

### Lazy Import

프로바이더 백엔드는 `get_backend()`에서 lazy import:

```python
def get_backend(kind: str) -> ProviderBackend:
    if kind == "openai":
        from agentouto.providers.openai import OpenAIBackend
        return OpenAIBackend()
```

이렇게 하면 사용하지 않는 프로바이더의 의존성이 import 시점에 필요하지 않다.

---

## 8. 캐싱 패턴

### 프로바이더 클라이언트 캐싱

```python
class OpenAIBackend:
    def __init__(self) -> None:
        self._clients: dict[str, AsyncOpenAI] = {}

    def _get_client(self, provider: Provider) -> AsyncOpenAI:
        if provider.name not in self._clients:
            self._clients[provider.name] = AsyncOpenAI(...)
        return self._clients[provider.name]
```

- 키: `provider.name`
- 패턴: 모든 프로바이더 백엔드에서 동일하게 사용

### 프로바이더 백엔드 캐싱

```python
class Router:
    def _get_backend(self, kind: str) -> ProviderBackend:
        if kind not in self._backends:
            self._backends[kind] = get_backend(kind)
        return self._backends[kind]
```

- 키: `provider.kind`
- Router에서 관리

### 모델별 max_tokens 캐싱

```python
_max_tokens_cache: dict[str, int] = {}  # 모듈 레벨 딕셔너리
```

- 키: `agent.model`
- Anthropic 백엔드에서 관리
- probe 성공 시만 캐시 (네트워크/인증 에러 시 캐시 안 함)

---

## 9. 문서화

### 코드 내 주석

- 최소화. 코드가 자명하면 주석 불필요.
- "왜"에 대한 주석만 작성. "무엇"은 코드가 말한다.

### Docstring

- 도구 함수의 docstring은 LLM에게 도구 설명으로 제공되므로 중요.
- 내부 함수의 docstring은 선택.

### AI 문서 (`ai-docs/`)

- 기술적 결정, 설계 의도, 패턴 설명은 여기에.
- 코드 내 주석 대신 이 문서에 기록.

---

## 10. 테스트

### 도구

- `pytest` + `pytest-asyncio` (asyncio_mode = `auto`)
- `mypy` 타입 체크
- `unittest.mock` — `patch`, `MagicMock`

### 테스트 파일 구조

```
tests/
├── __init__.py
├── conftest.py          # 공유 fixture
├── test_core.py         # Message, Agent, Provider, Tool, Context 단위 테스트
├── test_router.py       # Router 단위 테스트
├── test_event_log.py    # EventLog, Trace, Span 단위 테스트
└── test_runtime.py      # Runtime 통합 테스트 (MockBackend 기반)
```

### MockBackend 패턴

LLM 호출을 모킹하기 위해 `ProviderBackend`를 상속한 `MockBackend`를 사용한다:

```python
class MockBackend(ProviderBackend):
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self._call_count = 0

    async def call(self, context, tools, agent, provider) -> LLMResponse:
        response = self._responses[self._call_count]
        self._call_count += 1
        return response
```

`get_backend`를 패치하여 MockBackend를 주입한다:

```python
with patch("agentouto.router.get_backend", return_value=mock):
    result = await async_run(...)
```

패치 위치는 `agentouto.router.get_backend` (사용하는 쪽에서 패치).

### 헬퍼 함수

테스트에서 자주 사용하는 LLMResponse 생성 헬퍼:

```python
def _finish(message: str) -> LLMResponse          # finish 도구 호출
def _text(content: str) -> LLMResponse              # 텍스트 응답
def _tool_call(tool_name, tool_id, **kwargs)         # 도구 호출
def _call_agent(agent_name, message)                 # 에이전트 호출
```

---

## 11. CI/CD

### GitHub Actions

```
.github/workflows/
├── ci.yml       # push/PR시: pytest + mypy (Python 3.11, 3.12, 3.13)
└── publish.yml  # v* 태그 push시: PyPI Trusted Publisher로 자동 배포
```

- CI: `pip install -e '.[dev]'` → `pytest tests/ -v` → `mypy agentouto/`
- CD: v* 태그 push → `python -m build` → `pypa/gh-action-pypi-publish` (OIDC, 토큰 불필요)

---

## 12. Keyword-only 파라미터

선택적 파라미터는 keyword-only로 강제한다:

```python
# ✅ Good
async def async_run(
    entry: Agent,
    message: str,
    agents: list[Agent],
    tools: list[Tool],
    providers: list[Provider],
    *,
    debug: bool = False,
) -> RunResult:

# ❌ Bad
async def async_run(
    ...,
    debug: bool = False,  # positional로 호출 가능 — 불안전
) -> RunResult:
```

`*` 뒤의 파라미터는 반드시 `debug=True` 형식으로 전달해야 한다.

---

## 13. 금지 사항

| 하지 마라 | 이유 |
|----------|------|
| `Any`로 캐스팅 | 타입 안전성 파괴 |
| 전역 상태 변경 (Google 백엔드 제외) | 동시성 문제 |
| 동기 API 호출 | 비동기 런타임 블로킹 |
| 에이전트별 도구/호출 제한 | 철학 위배 |
| 새 메시지 타입 추가 | 철학 위배 |
| 불필요한 추상화 | 단순성 유지 |
