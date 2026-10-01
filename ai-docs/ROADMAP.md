# Roadmap — 로드맵

이 문서는 현재 상태, 계획된 기능, 알려진 문제를 관리한다.

**이 문서는 매 작업 완료 시 반드시 갱신해야 한다.**

---

## 1. 현재 상태

**버전:** 0.28.0 (공개)

**최종 업데이트:** coreouto 루프 통합 + 종료 정책 변경 (Phase 27)

---

## 2. 완료된 기능

### Phase 1: 코어 클래스 ✅

- [x] `Provider` 데이터클래스 — API 접속 정보 관리
- [x] `Agent` 데이터클래스 — 에이전트 설정 (모델, 추론 등)
- [x] `Tool` 데코레이터/클래스 — 함수 → 도구 변환, JSON Schema 자동 생성
- [x] `Message` 데이터클래스 — 전달/반환 메시지
- [x] 예외 계층 — `ProviderError`, `AgentError`, `ToolError`, `RoutingError`

### Phase 2: 단일 에이전트 실행 ✅

- [x] 에이전트 루프 (`_run_agent_loop`) — LLM 호출 → 도구 실행 → 반복
- [x] 도구 실행 — 동기/비동기 도구 함수 지원
- [x] 시스템 프롬프트 자동 생성
- [x] 도구 스키마 자동 생성 (사용자 도구 + call_agent + finish)
- [x] Context 관리 — 프로바이더 비의존적 대화 이력

### Phase 3: 멀티 에이전트 ✅

- [x] `call_agent` 도구 — 에이전트 간 호출
- [x] `finish` 도구 — 작업 완료 및 반환
- [x] 메시지 라우팅 — Router 클래스
- [x] 재귀적 에이전트 호출 — 독립적 Context

### Phase 4: 병렬 호출 ✅

- [x] `asyncio.gather` 기반 동시 에이전트 실행
- [x] 에러 내성 — 개별 실패가 전체를 중단하지 않음
- [x] 병렬 도구 호출 지원

### 프로바이더 백엔드 ✅

- [x] OpenAI 백엔드 — 클라이언트 캐싱, reasoning 지원, 안전한 JSON 파싱
- [x] Anthropic 백엔드 — extended thinking, temperature 강제, content block 처리
- [x] Google Gemini 백엔드 — protobuf 기반, thinking_config, JSON Schema 변환
- [x] 통일 파라미터 매핑 (max_output_tokens, reasoning, temperature)
- [x] API 에러 → ProviderError 래핑

### 인프라 ✅

- [x] `pyproject.toml` — 빌드 설정, 의존성
- [x] 공개 API 엑스포트 (`__init__.py`)
- [x] `run()` 동기 진입점
- [x] `async_run()` 비동기 진입점
- [x] `_constants.py` — 공유 상수

### Phase 5: 스트리밍, 로그, 디버그 ✅

- [x] 스트리밍 응답 — `async_run_stream()` + `StreamEvent` + OpenAI 네이티브 스트리밍
- [x] 로깅 시스템 — `EventLog` + `AgentEvent` (구조화된 이벤트 기록)
- [x] `Message` 객체 실제 생성/추적 — 런타임에서 전달/반환 Message 생성, `RunResult.messages`로 제공
- [x] 호출 트레이싱 — `Trace` + `Span` (call_id/parent_call_id 기반 트리 구조)
- [x] 디버그 모드 — `debug=True` 파라미터, Python `logging` 모듈 연동

### Phase 6: 배포 + 문서 ✅

- [x] CI/CD 설정 — GitHub Actions (CI: test + mypy, CD: PyPI Trusted Publisher, v* 태그 push 트리거)
- [x] 테스트 작성 — 61개 테스트 (pytest + pytest-asyncio, MockBackend 기반)
- [x] GitHub 레포 공개 — `llaa33219/agentouto`
- [x] PyPI 공개 — Trusted Publisher OIDC로 v0.2.0 배포 완료 (`pip install agentouto`)
- [ ] 사용자 문서 (예제 중심)
- [ ] API 레퍼런스 문서 자동 생성

### Phase 7: 멀티모달 첨부파일 ✅

- [x] `Attachment` 데이터클래스 — mime_type, data (base64), url, name
- [x] `ToolResult` 데이터클래스 — 도구가 텍스트 + 첨부파일을 함께 반환
- [x] `ContextMessage.attachments` 필드 추가
- [x] `Context.add_user()` / `add_tool_result()` 첨부파일 지원
- [x] `Message.attachments` 필드 추가
- [x] `run()` / `async_run()` / `async_run_stream()` 에 `attachments` 파라미터 추가
- [x] Runtime: attachments 전달 파이프라인 + ToolResult 분기 처리
- [x] OpenAI 백엔드: image_url, input_audio 첨부파일 변환
- [x] Anthropic 백엔드: image (base64/url), document (PDF) 첨부파일 변환
- [x] Google 백엔드: inline_data (Blob), file_data (FileData) 첨부파일 변환
- [x] 74개 테스트 (Attachment, ToolResult, 첨부파일 전달 테스트 포함)
- [x] 하위 호환성 100% 보장 — 모든 새 파라미터 기본값 None

### Phase 8: 리치 파라미터 스키마 ✅

- [x] `Annotated[T, "설명"]` → JSON Schema `description` 지원
- [x] `Literal["a", "b"]` → `enum` 지원
- [x] `enum.Enum` 서브클래스 → `enum` 지원
- [x] 기본값 → `default` 필드 + `required`에서 제외
- [x] 87개 테스트 (+15개)

### Phase 9: 추론 태그 처리 ✅

- [x] `providers/__init__.py`: `_content_outside_reasoning()` 유틸리티 추가
- [x] `LLMResponse.content_without_reasoning` 속성 추가
- [x] 추론 태그 내 도구 호출 감지 방지 인프라 구축
- [x] context.py에서 assistant content 원본 그대로 보존
- [x] 111개 테스트

### Phase 10: 자동 최대 출력 토큰 + 안전한 JSON 파싱 ✅

- [x] `agent.py`: `max_output_tokens` 기본값 `4096` → `None` (자동 최대값)
- [x] OpenAI/Google: `None`이면 max tokens 파라미터 생략 → API 자동 최대값
- [x] Anthropic: probe trick으로 최대값 자동 탐색 (`_PROBE_MAX_TOKENS = 999_999_999`)
- [x] `_parse_max_tokens_from_error()` + 모델별 캐시
- [x] OpenAI: `{"raw": ...}` 폴백 제거 → `_parse_tool_arguments()` 대체
- [x] `_repair_incomplete_json()` — 토큰 제한으로 잘린 JSON 복구
- [x] 마크다운 코드펜스 자동 제거
- [x] 141개 테스트

### Phase 11: Anthropic 네이티브 스트리밍 ✅

- [x] `call()` 내부적으로 스트리밍 기반으로 변경 (10분 타임아웃 문제 해결)
- [x] `stream()` 네이티브 구현 (텍스트 청크 실시간 yield)
- [x] 공유 `_stream_response()` 제너레이터로 코드 중복 제거
- [x] 스트리밍 이벤트 파싱: text_delta, input_json_delta, content_block_start
- [x] probe trick 스트리밍 컨텍스트에서도 동작
- [x] 141개 테스트

### Phase 12: finish() 강제화 ✅ (→ Phase 27에서 대체됨)

- [x] 텍스트 전용 응답 시 `finish` 사용 유도 — context에 안내 메시지 추가 후 재시도
- [x] 재시도 횟수 제한 없음 — 철학에 따라 시스템 레벨 제한 불허
- [x] `_run_agent_loop` + `_stream_agent_loop` 모두 적용
- [x] 시스템 프롬프트에서 finish 사용 강조
- [x] 143개 테스트

> **Phase 27에서 대체됨.** coreouto 루프 전환으로 텍스트 전용 응답이 그대로 최종 답이 되므로, 강제 유도 장치는 제거되었다. `finish(message=X)`는 그대로 남아 `X`를 결과로 반환하며(내부적으로 텍스트 응답으로 정규화), 시스템 프롬프트는 `finish`와 일반 텍스트 응답이 모두 결과를 전달한다고 안내한다. Phase 3의 `finish` 도구 자체는 유지된다.

### Phase 14: 에이전트/도구 혼동 에러 핸들링 ✅

- [x] `_resolve_agent_target()` — 에이전트 호출 시 도구/에이전트 혼동 감지 + 존재하지 않는 이름에 사용 가능 목록 포함
- [x] `_resolve_tool_target()` — 도구 호출 시 에이전트/도구 혼동 감지 + 존재하지 않는 이름에 사용 가능 목록 포함
- [x] `_execute_tool_call` — 혼동 감지 헬퍼 사용으로 개선된 에러 메시지 (비스트리밍)
- [x] `_stream_agent_loop` — 에이전트/도구 해석 및 서브 에이전트 실행 에러를 try/except로 크래시 방지 (스트리밍)
- [x] 에러가 도구 결과로 LLM에 전달 → LLM이 자기 수정 가능
- [x] 9개 신규 테스트 (비스트리밍 5개 + 스트리밍 4개)
- [x] 153개 테스트, mypy clean
- [x] ai-docs 업데이트 (ARCHITECTURE, ROADMAP)

### Phase 15: OAuth 인증 ✅

- [x] `auth/` 모듈 신규 생성 (7개 파일)
- [x] `AuthMethod` ABC — `get_token()`, `ensure_authenticated()`, `is_authenticated`
- [x] `TokenData` 데이터클래스 — access_token, refresh_token, expires_at, scopes, extra
- [x] `TokenStore` — `~/.agentouto/tokens/` 토큰 영속 저장 (파일: `0o600`, 디렉토리: `0o700`)
- [x] `ApiKeyAuth` — 정적 API 키 래퍼 (하위 호환)
- [x] `OpenAIOAuth` — OpenAI OAuth 2.0 + PKCE (✅ 활성 상태)
- [x] `ClaudeOAuth` — Anthropic Claude OAuth (⚠️ TOS 제한, 기본 client_id 주석 처리)
- [x] `GoogleOAuth` — Google Gemini/Antigravity OAuth (⚠️ TOS 제한, 기본 client_id 주석 처리)
- [x] `_oauth_common.py` — PKCE, 로컬 콜백 서버, 브라우저 인증, 토큰 교환 (`aiohttp` lazy import)
- [x] `Provider.auth` 필드 추가 + `resolve_api_key()` async 메서드
- [x] 4개 백엔드 모두 `provider.resolve_api_key()` 사용 + 토큰 로테이션 캐시 (`(api_key, client)` 튜플)
- [x] `AuthError` 예외 추가
- [x] `aiohttp` 선택적 의존성 (`pip install agentouto[oauth]`)
- [x] 공개 API 엑스포트: `AuthMethod`, `ApiKeyAuth`, `OpenAIOAuth`, `ClaudeOAuth`, `GoogleOAuth`, `TokenData`, `TokenStore`, `AuthError`
- [x] 153개 테스트 통과, 하위 호환성 100% 보장
- [x] ai-docs 전체 업데이트

### Phase 13: OpenAI Responses API 백엔드 ✅

- [x] `providers/openai_responses.py` 신규 생성 — `OpenAIResponsesBackend` 클래스
- [x] `client.responses.create()` 기반 `call()` 구현
- [x] `_build_input()` — Context → Responses API input items 변환 (user/assistant/function_call/function_call_output)
- [x] `_build_tools()` — 플랫 도구 스키마 변환 (`{"type": "function", "name":..., ...}`)
- [x] `_parse_response()` — `response.output`에서 function_call 아이템 추출, `output_text`로 텍스트 추출
- [x] `stream()` 네이티브 스트리밍 구현 (SSE 이벤트 파싱)
- [x] `_parse_tool_arguments` 재사용 (`providers/openai.py`에서 import)
- [x] 클라이언트 캐싱 (`AsyncOpenAI` 인스턴스 재사용)
- [x] 멀티모달 첨부파일 처리 (`input_image`, `input_audio`)
- [x] `provider.py`: `kind` Literal에 `"openai_responses"` 추가
- [x] `providers/__init__.py`: `get_backend()`에 분기 추가
- [x] `previous_response_id` 사용하지 않음 (스테이트리스 모드, 아키텍처 정합성 유지)
- [x] ai-docs 전체 업데이트 (ARCHITECTURE, PROVIDER_BACKENDS, ROADMAP)
- [x] README 업데이트 (Supported Providers 테이블, Provider 섹션)

### Phase 16: 대화 이력 (history) ✅

- [x] `run()`, `async_run()`, `async_run_stream()`에 `history` 파라미터 추가
- [x] `call_agent` 도구에 `history` 파라미터 추가 (LLM이 이전 대화 전달 가능)
- [x] `Message` 목록을 에이전트 컨텍스트 앞에 추가하여 이전 대화 참조 가능
- [x] 공개 API 엑스포트: `history` 파라미터
- [x] 186개 테스트 통과
- [x] README 업데이트

### Phase 17: 백그라운드 실행 ✅

- [x] `loop_manager.py` 신규 생성: `AgentLoopRegistry`, `MessageQueue`, `BackgroundAgentLoop`, `RegisteredAgentLoop`
- [x] `AgentLoopRegistry` — 스레드 세이프 싱글톤, 모든 실행 중 에이전트 루프 추적
- [x] `BackgroundAgentLoop` — 백그라운드 에이전트 실행 래퍼 (메시지 주입, 상태 관리)
- [x] `RegisteredAgentLoop` — 일반/백그라운드 에이전트 공용 루프 래퍼
- [x] `_run_agent_loop` — 모든 루프를 AgentLoopRegistry에 등록 (시작 시 register, 종료 시 unregister)
- [x] `_spawn_background_agent` — 백그라운드 에이전트 스폰 로직
- [x] `call_agent(background=True)` — 백그라운드에서 에이전트 실행
- [x] `send_message` 도구 — 실행 중인 에이전트에 메시지 주입
- [x] `get_messages` 도구 — 에이전트 상태/메시지 조회
- [x] 13개 신규 테스트 (test_background.py)
- [x] ai-docs 업데이트 (ARCHITECTURE, MESSAGE_PROTOCOL, ROADMAP)
- [x] README 업데이트

### Phase 18: 백그라운드 스트리밍 + 통합 API ✅

- [x] `run_background()` — async 백그라운드 스폰 API
- [x] `run_background_sync()` — sync 백그라운드 스폰 API
- [x] `send_message()` — 공개 API (send_message_to_background_agent 별칭)
- [x] `get_agent_status()` — 공개 API (get_background_agent_status 별칭)
- [x] `get_stream_events()` — 백그라운드 에이전트에서 스트리밍 이벤트 수신
- [x] `_run_agent_loop` try/finally로 모든 종료 경로에서 unregister 보장
- [x] 186개 테스트 통과
- [x] ai-docs 업데이트 (ARCHITECTURE, MESSAGE_PROTOCOL, ROADMAP)

### Phase 19: 런타임 extra_instructions 주입 ✅

- [x] `Runtime.__init__`에 `extra_instructions` 및 `extra_instructions_scope` 파라미터 추가
- [x] `Router.build_system_prompt`에 `extra_instructions` 파라미터 추가 — "ADDITIONAL INSTRUCTIONS" 섹션으로 시스템 프롬프트에 주입
- [x] `run()`, `async_run()`, `run_background()`, `run_background_sync()`에 `extra_instructions` 및 `extra_instructions_scope` 파라미터 추가
- [x] `extra_instructions_scope="entry"` — 진입 에이전트에만 주입 (기본값)
- [x] `extra_instructions_scope="all"` — call_agent로 호출되는 모든 하위 에이전트에도 전파
- [x] 200개 테스트 통과 (14개 신규 테스트)
- [x] ai-docs 업데이트 (ARCHITECTURE, ROADMAP)

### Phase 20: 시작 에이전트 + 에이전트 참여 풀 + 태그 출력 포맷 ✅

- [x] `starting_agents` 파라미터 — 동등한 에이전트들이 병렬로 시작 (순서 무관)
- [x] `entry` 파라미터 완전 제거
- [x] `run_agents` 파라미터 — 참여자 풀 (선택적, 기본값은 `starting_agents`)
- [x] `starting_agents`에 있지만 `run_agents`에 없는 에이전트에 대해 경고 발행
- [x] `Router`에 `_run_agents` 필드 추가 — 참여자 풀 기반 가시성/실행 제어
- [x] `build_system_prompt` — `run_agents` 기반 에이전트 필터링
- [x] `Runtime.execute` — `starting_agents` 병렬 실행 (asyncio.gather)
- [x] `run()`, `async_run()`, `run_background()`, `run_background_sync()`에 `starting_agents`, `run_agents` 파라미터 추가
- [x] 병렬 실행 결과 XML 태그 포맷: `[agent_name]content[/agent_name]`
- [x] `call_agent` 반환값에도 동일 포맷 적용
- [x] README 업데이트 (Starting Agents 섹션, Parallel Output Format 섹션, Development Status)
- [x] ai-docs/AGENT_LIST_ISOLATION.md 완전 재작성
- [x] ai-docs/ROADMAP.md 업데이트

### Phase 21: 기본 도구 오버라이드/비활성화 ✅

- [x] `_constants.py`: `BUILTIN_TOOL_NAMES` frozenset 추가
- [x] `Router.__init__`: `disabled_tools` 파라미터 + 사용자 도구를 일반 도구와 오버라이드로 분리
- [x] `Router.build_tool_schemas`: `_builtin_tool_schemas()` 헬퍼로 분리, disable/override 반영
- [x] `Router._builtin_overrides`: 이름 매칭으로 기본 도구 교체 감지
- [x] `Runtime._execute_tool_call`: 오버라이드 우선 실행 → 비활성화 체크 → 기본 분기
- [x] `Runtime._run_agent_loop`: finish 오버라이드 지원
- [x] 스트리밍 경로에도 오버라이드/비활성화 분기 적용
- [x] `run()`, `async_run()`, `run_background()`, `run_background_sync()`, `async_run_stream()`에 `disabled_tools` 파라미터 추가
- [x] `finish` 비활성화 시 `ValueError` (오버라이드는 가능)
- [x] 오버라이드가 비활성화보다 우선
- [x] 6개 신규 테스트, 214개 전체 통과

### Phase 22: 에이전트 중간 메시지 (on_message) ✅

- [x] `loop_manager.py`: `RegisteredAgentLoop`에 `caller_loop_id`, `on_message` 콜백 추가
- [x] `RegisteredAgentLoop.inject_message`: 메시지 주입 시 `on_message` 콜백 호출 (예외 안전)
- [x] `Router.build_system_prompt`: `caller_loop_id` 파라미터 → INVOKED BY 섹션에 task_id 안내 포함
- [x] `Runtime.__init__`: `on_message` 파라미터 추가
- [x] `Runtime._execute_single`: 유저 루프를 `AgentLoopRegistry`에 등록/해제
- [x] `Runtime._run_agent_loop`: `caller_loop_id` 파라미터 → `RegisteredAgentLoop` + `build_system_prompt`에 전달
- [x] `Runtime._execute_tool_call`: `current_loop_id` → 서브 에이전트에 `caller_loop_id`로 전달
- [x] `send_message` 처리에서 `self._messages` 추적 추가
- [x] `run()`, `async_run()`, `async_run_stream()`에 `on_message` 파라미터 추가
- [x] 스트리밍: `StreamEvent.type`에 `"user_message"` 추가
- [x] `Runtime.execute_stream`: 유저 루프 등록 + `user_message` 이벤트 yield
- [x] `__init__.py`: `BUILTIN_TOOL_NAMES` 공개 API 엑스포트
- [x] 8개 신규 테스트, 214개 전체 통과

### Phase 23: 백그라운드 에이전트 기본 비활성화 ✅

- [x] `Router.__init__`: `allow_background_agents: bool = False` 파라미터 추가
- [x] `Router._builtin_tool_schemas`: `allow_background_agents=False`일 때 `spawn_background_agent`와 `call_agent`의 `background` 파라미터 제외
- [x] `Router.build_system_prompt`: `allow_background_agents=False`일 때 BACKGROUND EXECUTION 섹션 제외
- [x] `Runtime.__init__`: `allow_background_agents: bool = False` 파라미터 추가
- [x] `Runtime._execute_tool_call`: `allow_background_agents=False`일 때 `call_agent(background=True)`와 `spawn_background_agent` 호출 시 에러 반환
- [x] `run()`, `async_run()`, `run_background()`, `run_background_sync()`, `async_run_stream()`에 `allow_background_agents` 파라미터 추가
- [x] 테스트 업데이트: `test_background.py`의 `_mk_runtime` 헬퍼에 `allow_background_agents` 파라미터 추가
- [x] 테스트 업데이트: `test_router.py`에 기본값 테스트 + `allow_background_agents=True` 테스트 추가
- [x] 2개 신규 테스트, 219개 전체 통과
- [x] README 업데이트 (Background Execution 섹션, Tool Override/Disable 섹션)
- [x] ai-docs 업데이트 (ARCHITECTURE, MESSAGE_PROTOCOL, ROADMAP)

### Phase 24: 요약 시 다음 작업 계획 자동 생성 ✅

- [x] `summarizer.py`: `SummaryResult` dataclass 추가 (`summary`, `next_steps` 필드)
- [x] `summarizer.py`: `parse_summary_response()` 함수 추가 — `<summary>` / `<next_steps>` 태그 파싱
- [x] `summarizer.py`: `build_self_summarize_context()` 프롬프트 수정 — 다음 작업 계획 생성 지시 + 태그 형식 지정
- [x] `runtime.py`: `_maybe_summarize()` 수정 — 요약 후 `next_steps`가 있으면 컨텍스트에 시스템 메시지로 주입
- [x] `runtime.py`: `parse_summary_response` import 추가
- [x] 테스트 추가: `test_summarizer.py`에 `parse_summary_response` 테스트 케이스 추가
- [x] ai-docs 업데이트 (ARCHITECTURE.md, ROADMAP.md)

### Phase 25: 요약 사용자 후킹 (`on_summarize` 콜백) ✅

- [x] `summarizer.py`: `SummarizeInfo` dataclass 추가 (`agent_name`, `messages_to_summarize`, `summary`, `next_steps`, `tokens_before`, `tokens_after`)
- [x] `runtime.py`: `Runtime.__init__`에 `on_summarize` 파라미터 추가
- [x] `runtime.py`: `_maybe_summarize()` 수정 — 요약 생성 후 `on_summarize` 콜백 호출, 반환값으로 summary 대체 가능
- [x] `runtime.py`: `async_run()`에 `on_summarize` 파라미터 추가
- [x] `runtime.py`: `run()`에 `on_summarize` 파라미터 추가
- [x] `runtime.py`: `run_background()`에 `on_summarize` 파라미터 추가
- [x] `runtime.py`: `run_background_sync()`에 `on_summarize` 파라미터 추가
- [x] `streaming.py`: `async_run_stream()`에 `on_summarize` 파라미터 추가
- [x] `__init__.py`: `SummarizeInfo` 공개 API 엑스포트 추가
- [x] 테스트 추가: `test_summarizer.py`에 `on_summarize` 콜백 테스트 3개 추가 (정보 수신, summary 대체, 에러 무시)
- [x] ai-docs 업데이트 (ARCHITECTURE.md, ROADMAP.md)

### Phase 26: API 토큰 사용량 추적 + 하이브리드 요약 트리거 ✅

- [x] `providers/__init__.py`: `Usage` 데이터클래스 추가 (`input_tokens`, `output_tokens`, `total_tokens` 프로퍼티, `__add__`/`__iadd__`)
- [x] `providers/__init__.py`: `LLMResponse`에 `usage: Usage | None` 필드 추가
- [x] `providers/openai.py`: `response.usage.prompt_tokens`/`completion_tokens` 추출, 스트리밍에 `stream_options={"include_usage": True}` 추가
- [x] `providers/openai_responses.py`: `response.usage.input_tokens`/`output_tokens` 추출, 스트리밍에서 `response.done` 이벤트 처리
- [x] `providers/anthropic.py`: `message_start`에서 `input_tokens`, `message_delta`에서 `output_tokens` 추출
- [x] `providers/google.py`: `response.usage_metadata.prompt_token_count`/`candidates_token_count` 추출
- [x] `runtime.py`: `RunResult`에 `token_usage: Usage` 필드 추가
- [x] `runtime.py`: `Runtime._token_usage` 필드로 모든 LLM 호출의 토큰 누적
- [x] `runtime.py`: `_accumulate_usage(response)` 메서드 — LLM 응답의 usage를 누적
- [x] `runtime.py`: `_estimate_current_tokens(context)` 메서드 — 하이브리드 토큰 추정 (실제 API 토큰 + 새 메시지 추정)
- [x] `runtime.py`: `_last_input_tokens`, `_last_message_count` 필드로 실제 토큰 기반 추적
- [x] `runtime.py`: `_maybe_summarize()`에서 `_estimate_current_tokens()` 사용으로 요약 트리거 정확도 향상
- [x] `__init__.py`: `Usage` 공개 API 엑스포트 추가
- [x] 229개 테스트 통과
- [x] ai-docs 업데이트 (ARCHITECTURE, PROVIDER_BACKENDS, ROADMAP)

### Phase 27: coreouto 루프 통합 ✅

- [x] `pyproject.toml`: `coreouto>=0.11.3,<0.12` 의존성 추가 (버전 고정)
- [x] `agentouto/_bridge/` 패키지 추가 — `coreouto`를 import하는 유일한 곳
  - [x] `convert.py` — Context ↔ coreouto Message, Attachment ↔ ContentBlock, LLMResponse ↔ coreouto LLMResponse, Usage 변환
  - [x] `state.py` — `RunState` + `_RUN_STATE` ContextVar (coreouto 레지스트리가 프로세스 전역이므로 실행 단위 상태를 컨텍스트로 전달)
  - [x] `provider.py` — `DispatchProvider` (coreouto Provider 프로토콜 구현). `router.get_backend` 경유로 테스트 심 유지, `finish` 호출을 텍스트 응답으로 정규화
  - [x] `tools.py` — builtin + 사용자 도구 디스패치, coreouto 도구 레지스트리 등록, 기존 에러 문자열 보존
  - [x] `hooks.py` — coreouto 훅 → StreamEvent / EventLog / summarizer 연결
- [x] `runtime.py`: 턴 루프를 `coreouto.Agent.call()`로 대체 (1584 → 800 LOC)
- [x] `_stream_agent_loop` 제거 — 스트리밍은 같은 루프에 스트림 콜백이 붙은 경로
- [x] finish 강제 유도 장치 제거 — 텍스트 전용 응답이 곧 최종 답 (coreouto 컨벤션)
- [x] `providers/__init__.py`: `LLMResponse.stop_reason` 필드 추가 + 4개 백엔드에서 벤더 종료 사유 전달
- [x] `router.py`: finish 도구 설명과 시스템 프롬프트 IMPORTANT 블록을 "finish 또는 일반 텍스트 응답 둘 다 결과를 전달"으로 수정
- [x] 공개 Python API 변경 없음 (엔트리포인트 시그니처, 데이터클래스, 도구 스키마, 출력 포맷 모두 동일)
- [x] ai-docs 업데이트 (ARCHITECTURE, MESSAGE_PROTOCOL, PROVIDER_BACKENDS, PHILOSOPHY, CONVENTIONS, ROADMAP)

---

## 3. 미구현 기능

### 추가 고려 사항
- [ ] Google GCP OAuth 2.0 (자체 GCP 프로젝트 기반, 공식 지원 무료 티어)
- [ ] 비용 추적
- [ ] 타임아웃 설정 (에이전트 레벨)
- [ ] 재시도 로직 (프로바이더 레벨)
- [ ] 콜백/이벤트 훅

---

## 4. 알려진 문제

| 문제 | 심각도 | 설명 |
|------|--------|------|
| Google 전역 설정 충돌 | 중간 | `genai.configure()`가 전역이므로 여러 Google Provider 동시 사용 시 충돌 가능 |
| 무한 루프 방지 없음 | 낮음 (설계 의도) | 시스템 레벨 제한 없음. instructions로만 제어. 철학적 결정. |
| 스트리밍은 Google만 fallback | 낮음 | Google은 fallback (non-streaming 후 단일 이벤트). OpenAI, Anthropic은 네이티브 스트리밍 |
| 멀티모달 프로바이더별 지원 범위 | 낮음 | OpenAI: image/audio, Anthropic: image/PDF, Google: 모든 타입. 미지원 타입은 조용히 무시 |
| Anthropic max_tokens probe 레이스 컨디션 | 낮음 | 동일 모델 동시 호출 시 여러 번 probe 가능. 첫 성공 후 캐시 |
| async_run_stream 다중 starting_agents 미지원 | 중간 | `async_run_stream`은 `starting_agents[0]`만 실행. `run()`/`async_run()`과 달리 다중 병렬 에이전트 미지원. 문서에서는 `starting_agents` 파라미터를 선언하지만 실제 동작은 단일 에이전트만 처리 |

---

## 5. 변경 이력

### 0.28.0 (Phase 27: coreouto 루프 통합)

- Phase 27 완료: `coreouto==0.11.3` 도입 및 에이전트 루프 내부 재작성
  - `pyproject.toml`: `coreouto>=0.11.3,<0.12` 의존성 추가
  - `agentouto/_bridge/` 추가 — coreouto 어댑터 (convert / state / provider / tools / hooks)
  - `runtime.py`: 자체 구현 턴 루프를 `coreouto.Agent.call()`로 대체 (1584 → 800 LOC)
  - `_stream_agent_loop` 제거 — 스트리밍이 같은 루프의 스트림 콜백 경로로 통합
  - 텍스트 전용 응답이 곧 최종 답이 되도록 종료 정책 변경 (finish 강제 유도 장치 제거)
  - `providers/*`: `LLMResponse.stop_reason` 추가 및 벤더 종료 사유 전달
  - `router.py`: finish 설명과 시스템 프롬프트를 "finish 또는 일반 텍스트 둘 다 전달"으로 수정
  - 공개 API는 변경 없음
  - ai-docs 전체 업데이트

### 0.27.0 (Phase 26: API 토큰 사용량 추적 + 하이브리드 요약 트리거)

- Phase 26 완료: API 토큰 사용량 추적 및 하이브리드 요약 트리거
  - `providers/__init__.py`: `Usage` 데이터클래스 추가 (`input_tokens`, `output_tokens`, `total_tokens`, `__add__`/`__iadd__`)
  - `providers/__init__.py`: `LLMResponse`에 `usage: Usage | None` 필드 추가
  - 모든 프로바이더 백엔드에서 API 응답의 토큰 사용량 추출:
    - OpenAI Chat Completions: `response.usage.prompt_tokens`/`completion_tokens`, 스트리밍에 `stream_options` 추가
    - OpenAI Responses API: `response.usage.input_tokens`/`output_tokens`, 스트리밍에서 `response.done` 이벤트 처리
    - Anthropic: `message_start`에서 `input_tokens`, `message_delta`에서 `output_tokens` 추출
    - Google Gemini: `response.usage_metadata.prompt_token_count`/`candidates_token_count` 추출
  - `runtime.py`: `RunResult.token_usage` 필드로 누적 토큰 사용량 제공
  - `runtime.py`: `_accumulate_usage()`로 매 LLM 호출마다 토큰 누적
  - `runtime.py`: `_estimate_current_tokens()`로 하이브리드 토큰 추정 (실제 API 토큰 + 새 메시지 추정)
  - `runtime.py`: 요약 트리거가 실제 토큰 기반으로 동작하여 정확도 향상
  - `__init__.py`: `Usage` 공개 API 엑스포트
  - 229개 테스트 통과
  - ai-docs 업데이트 (ARCHITECTURE, PROVIDER_BACKENDS, ROADMAP)

### 0.24.0 (Phase 21-22: 기본 도구 오버라이드/비활성화 + 에이전트 양방향 메시지)

- Phase 21 완료: 기본 도구 오버라이드/비활성화
  - `_constants.py`: `BUILTIN_TOOL_NAMES` frozenset 추가
  - `Router.__init__`: `disabled_tools` 파라미터 + 사용자 도구 분리 (_tools / _builtin_overrides)
  - `Router.build_tool_schemas`: `_builtin_tool_schemas()` 헬퍼, disable/override 반영
  - `Runtime._execute_tool_call`: 오버라이드 우선 → 비활성화 체크 → 기본 분기
  - `Runtime._run_agent_loop`: finish 오버라이드 지원
  - 스트리밍 경로에도 오버라이드/비활성화 적용
  - `run()`, `async_run()`, `run_background()`, `run_background_sync()`, `async_run_stream()`에 `disabled_tools` 파라미터
  - `finish` 비활성화 불가 (`ValueError`), 오버라이드 가능
  - 오버라이드 > 비활성화 우선순위
- Phase 22 완료: 에이전트 중간 메시지 (양방향)
  - `RegisteredAgentLoop`: `caller_loop_id`, `on_message` 콜백 추가
  - `Router.build_system_prompt`: `caller_loop_id` → INVOKED BY에 task_id 안내
  - `Runtime._execute_single`: 유저 루프를 AgentLoopRegistry에 등록/해제 + 유저→에이전트 큐 생성
  - `Runtime._run_agent_loop`: `caller_loop_id` → RegisteredAgentLoop + build_system_prompt 전달
  - `Runtime._execute_tool_call`: `current_loop_id` → 서브 에이전트에 caller_loop_id로 전달
  - `send_message` 처리에서 `self._messages` 추적
  - **`on_message` 시그니처 변경**: `(msg)` → `(msg, send)` — 유저가 `send()`로 에이전트에게 메시지 전송 가능
  - `_run_agent_loop`: 매 반복마다 유저 큐 확인 → `context.add_user()`로 컨텍스트 주입
  - `run()`, `async_run()`, `async_run_stream()`에 `on_message` 파라미터
  - `StreamEvent.type`에 `"user_message"` 추가
  - `execute_stream`: 유저 루프 등록 + user_message 이벤트 yield
  - `__init__.py`: `BUILTIN_TOOL_NAMES` 공개 API
  - **`run()`과 `run_background()`의 기능적 차이는 블로킹/백그라운드 뿐** — 양방향 메시지는 동일 지원
- 테스트 200개 → 216개 (+16)
- 철학 준수: 원칙 3 (run 레벨 도구 커스터마이즈), 원칙 4 (forward 타입 사용), 원칙 5 (같은 send_message 메커니즘)

### 0.23.0 (시작 에이전트 + 에이전트 가시성 스코핑 + 태그 출력 포맷)

- Phase 20 완료: 시작 에이전트, 에이전트 가시성 스코핑, 태그 출력 포맷
- `starting_agents` 파라미터 — 동등한 에이전트들이 병렬로 시작 (순서 무관, entry 개념 없음)
- `run_agents` 파라미터 — 에이전트 풀 선언 + 가시성 스코프 (agents 대체)
- `agents` 파라미터 deprecated — 하위 호환 유지, `run_agents` 우선
- `Router._run_agents` 필드 + `build_system_prompt` 필터링
- `Runtime.execute` — `starting_agents` 병렬 실행 (asyncio.gather)
- `run()`, `async_run()`, `run_background()`, `run_background_sync()`에 `starting_agents`, `run_agents` 추가
- 병렬 실행 결과 XML 태그 포맷: `[agent_name]content[/agent_name]`
- `call_agent` 반환값에도 동일 포맷 적용
- README大幅更新 (Starting Agents, Parallel Output Format 섹션新增)
- ai-docs/ROADMAP.md 업데이트

### 0.21.0 (런타임 extra_instructions 주입)

- Phase 19 완료: 런타임 extra_instructions 주입
- `Runtime.__init__`에 `extra_instructions` 및 `extra_instructions_scope` 파라미터 추가
- `Router.build_system_prompt`에 `extra_instructions` 파라미터 추가
- `run()`, `async_run()`, `run_background()`, `run_background_sync()`에 `extra_instructions` 및 `extra_instructions_scope` 파라미터 추가
- `extra_instructions_scope="entry"` — 진입 에이전트에만 주입 (기본값)
- `extra_instructions_scope="all"` — call_agent로 호출되는 모든 하위 에이전트에도 전파
- 200개 테스트 (14개 신규)

### 0.20.4 (백그라운드 실행 + 인터-에이전트 메시징)

- Phase 17, 18 완료: 백그라운드 실행 및 인터-에이전트 메시징
- `loop_manager.py` 신규: AgentLoopRegistry, MessageQueue, BackgroundAgentLoop, RegisteredAgentLoop
- `_run_agent_loop` — 모든 루프를 AgentLoopRegistry에 등록/해제
- `run_background()` / `run_background_sync()` — 백그라운드 에이전트 스폰
- `send_message()` / `get_agent_status()` / `get_stream_events()` — 공개 API
- `call_agent(background=True)` — 백그라운드 에이전트 내부 호출
- try/finally로 모든 종료 경로에서 unregister 보장
- 186개 테스트

### 0.18.0 (시스템 프롬프트 강화)

- router.py: `build_system_prompt()`에 `caller` 파라미터 추가
- runtime.py: 에이전트 호출 시 호출자 정보 전달 (`_run_agent_loop`, `_execute_tool_call`, streaming 버전)
- 시스템 프롬프트에 INVOKED BY 섹션 추가 — 호출한 에이전트 표시
- 시스템 프롬프트에 PARALLEL EXECUTION 가이드 추가 — 여러 에이전트 동시 호출 방법 명시
- 시스템 프롬프트에 COLLABORATION GUIDELINES 추가 — 협업, 역할 준수, 적극적 참여 지시
- MESSAGE_PROTOCOL.md 시스템 프롬프트 예시 업데이트
- 테스트 173개

### 0.11.0 (Phase 15: OAuth 인증)

- `auth/` 모듈 신규 생성 (7개 파일): AuthMethod ABC, TokenData, TokenStore, ApiKeyAuth, OpenAIOAuth, ClaudeOAuth, GoogleOAuth, _oauth_common
- `Provider.auth: AuthMethod | None` 필드 추가 + `resolve_api_key()` async 메서드
- 4개 백엔드: `provider.api_key` → `await provider.resolve_api_key()` + 토큰 로테이션 캐시 `(api_key, client)` 튜플
- `AuthError(provider_name, message)` 예외 추가
- `aiohttp` 선택적 의존성 (`pip install agentouto[oauth]`)
- 공개 API: AuthMethod, ApiKeyAuth, OpenAIOAuth, ClaudeOAuth, GoogleOAuth, TokenData, TokenStore, AuthError
- ClaudeOAuth: ⚠️ Anthropic TOS 제한 경고 + 기본 client_id 주석 처리
- GoogleOAuth: ⚠️ Google Antigravity TOS 제한 경고 + 기본 client_id 주석 처리
- 테스트 153개, 하위 호환성 100% 보장
- ai-docs 전체 업데이트 (ARCHITECTURE, PROVIDER_BACKENDS, ROADMAP, CONVENTIONS)
- README 업데이트 (OAuth 섹션, Provider 테이블, Package Structure, Development Status)

### 0.10.1 (Phase 14: 에이전트/도구 혼동 에러 핸들링)

- runtime.py: `_resolve_agent_target()` / `_resolve_tool_target()` DRY 헬퍼 추가
- 에이전트/도구 혼동 감지 — 도구를 에이전트로 호출하거나 에이전트를 도구로 호출 시 안내 에러 메시지
- 존재하지 않는 이름 호출 시 사용 가능한 에이전트/도구 목록 포함
- `_stream_agent_loop` — 에이전트/도구 해석 + 서브 에이전트 실행 try/except 크래시 방지
- 에러는 크래시 대신 도구 결과로 LLM에 전달 → 자기 수정 가능
- 테스트 144개 → 153개 (+9개: 비스트리밍 5 + 스트리밍 4)
- ai-docs 업데이트 (ARCHITECTURE, ROADMAP)

### 0.10.0 (Phase 13: OpenAI Responses API 백엔드)

- `providers/openai_responses.py` 신규 생성: `OpenAIResponsesBackend` 클래스
- `client.responses.create()` 기반 `call()` + `stream()` 구현
- `_build_input()`: Context → input items 변환 (system_prompt → instructions 파라미터)
- `_build_tools()`: 플랫 도구 스키마 ({"type":"function","name":...})
- `_parse_response()`: response.output 파싱 (function_call items + output_text)
- 네이티브 스트리밍 (SSE 이벤트: output_text.delta, function_call_arguments.delta)
- `_parse_tool_arguments` 재사용 (openai.py에서 import)
- 멀티모달 첨부파일 처리 (input_image, input_audio)
- `provider.py`: kind Literal에 "openai_responses" 추가
- `providers/__init__.py`: get_backend() 분기 추가
- `previous_response_id` 사용하지 않음 (스테이트리스 모드)
- ai-docs 전체 업데이트
- README 업데이트

### 0.8.0 (Phase 12: finish() 강제화) — 이후 Phase 27에서 대체됨

- runtime.py: 텍스트 전용 응답 시 finish 유도 로직 추가 (`_run_agent_loop` + `_stream_agent_loop`)
- 재시도 횟수 제한 없음 — 철학에 따라 시스템 레벨 제한 불허
- router.py: 시스템 프롬프트에서 finish 사용 강조
- 에이전트의 일반 메시지 출력과 반환값의 명확한 분리
- 테스트 141개 → 143개
- ai-docs 업데이트 (MESSAGE_PROTOCOL, ARCHITECTURE, ROADMAP)

### 0.5.0 (Phase 9–10)

- Phase 9 완료: 추론 태그 처리
  - `providers/__init__.py`: `_content_outside_reasoning()` 유틸리티 추가
  - `LLMResponse.content_without_reasoning` 속성 추가
  - 추론 태그(`<think>`, `<thinking>`, `<reason>`, `<reasoning>`) 내 도구 호출 감지 방지
  - context.py에서 assistant content 원본 보존
- Phase 10 완료: 자동 최대 출력 토큰 + 안전한 JSON 파싱
  - `agent.py`: `max_output_tokens` 기본값 `4096` → `None`
  - OpenAI/Google: `None`이면 max tokens 파라미터 생략
  - Anthropic: probe trick (`_PROBE_MAX_TOKENS = 999_999_999`) + `_parse_max_tokens_from_error()` + 모델별 캐시
  - OpenAI: `{"raw": ...}` 폴백 → `_parse_tool_arguments()` + `_repair_incomplete_json()` 대체
- 테스트 87개 → 141개
- ai-docs 업데이트

### 0.4.0 (Phase 8: 리치 파라미터 스키마)

- Phase 8 완료: 리치 파라미터 스키마
  - `Annotated[T, "설명"]` → JSON Schema `description`
  - `Literal["a", "b"]` → `enum`
  - `enum.Enum` 서브클래스 → `enum`
  - 기본값 → `default` 필드 + `required`에서 제외
- 테스트 74개 → 87개

### 0.3.0 (Phase 7: 멀티모달)

- Phase 7 완료: 멀티모달 첨부파일 지원
- 새 데이터클래스: `Attachment` (context.py), `ToolResult` (tool.py)
- `ContextMessage.attachments` 필드 추가
- `Message.attachments` 필드 추가
- `run()`, `async_run()`, `async_run_stream()` 에 keyword-only `attachments` 파라미터 추가
- Runtime: attachments 전달 파이프라인, ToolResult 분기 처리
- `Tool.execute()` 반환 타입: `str` → `str | ToolResult`
- OpenAI 백엔드: `_build_attachment_parts()` — image_url, input_audio
- Anthropic 백엔드: `_build_attachment_blocks()` — image, document (PDF)
- Google 백엔드: `_build_attachment_parts()` — inline_data (Blob), file_data (FileData)
- 새 공개 API: `Attachment`, `ToolResult`
- 테스트 61개 → 74개 (Attachment, ToolResult, 첨부파일 전달 테스트 추가)
- 하위 호환성 100% 보장

### 0.2.0

- Phase 5 완료: 스트리밍, 로깅, 메시지 추적, 호출 트레이싱, 디버그 모드
- Phase 6 완료: GitHub repo, CI/CD, 테스트, PyPI 배포
- 새 모듈: `event_log.py`, `tracing.py`, `streaming.py`
- 새 공개 API: `EventLog`, `AgentEvent`, `Trace`, `Span`, `StreamEvent`, `async_run_stream`
- `RunResult` 확장: `messages`, `trace`, `event_log` 필드 추가, `format_trace()` 메서드
- `run()`/`async_run()`에 keyword-only `debug` 파라미터 추가
- `EventLog.filter(agent_name, event_type)` 메서드 추가
- OpenAI 백엔드에 네이티브 스트리밍 구현
- `ProviderBackend`에 `stream()` 기본 구현 (fallback) 추가
- `Router.stream_llm()` 메서드 추가
- Apache License 2.0 적용
- 패키지 리네이밍: `agnetouto` → `agentouto` (오타 수정)
- PyPI 배포 완료: Trusted Publisher OIDC, v* 태그 push 트리거
- CD 워크플로우: release 생성 → v* 태그 push 트리거로 변경
- README 영문화: 모든 한국어 텍스트 → 영어 번역
- AI 모델명 최신화: gpt-5.2, gpt-5.3-codex, claude-opus-4-6, claude-sonnet-4-6, gemini-3.1-pro, gemini-3-flash
- `logo.svg` 추가 및 README 상단 배치
- Supported Providers 테이블에 Anthropic 호환 서비스 추가 (AWS Bedrock, Vertex AI, Ollama, LiteLLM)

### 0.1.0 (초기 구현)

- Phase 1~4 완료
- OpenAI, Anthropic, Google 백엔드 구현
- 피어 간 자유 호출 아키텍처 구현
- 병렬 에이전트 호출 구현
- README.md 및 ai-docs 작성
