# Roadmap — 로드맵

이 문서는 현재 상태, 계획된 기능, 알려진 문제를 관리한다.

**이 문서는 매 작업 완료 시 반드시 갱신해야 한다.**

---

## 1. 현재 상태

**버전:** 0.5.0 (공개)

**최종 업데이트:** Phase 12 완료 — finish() 강제화

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

### Phase 12: finish() 강제화 ✅

- [x] 텍스트 전용 응답 시 `finish` 사용 유도 (nudge) — context에 안내 메시지 추가 후 재시도
- [x] 재시도 횟수 제한 없음 — 철학에 따라 시스템 레벨 제한 불허
- [x] `_run_agent_loop` + `_stream_agent_loop` 모두 적용
- [x] 시스템 프롬프트에서 finish 사용 강조
- [x] 경고 로그 출력 (LLM이 finish 사용 안 할 때)
- [x] 143개 테스트 (스트리밍 nudge 테스트 포함)

---

## 3. 미구현 기능

### 추가 고려 사항
- [ ] 토큰 사용량 추적
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

---

## 5. 변경 이력

### 0.8.0 (Phase 12: finish() 강제화)

- runtime.py: 텍스트 전용 응답 시 finish nudge 로직 추가 (`_run_agent_loop` + `_stream_agent_loop`)
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
