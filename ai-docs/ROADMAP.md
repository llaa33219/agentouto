# Roadmap — 로드맵

이 문서는 현재 상태, 계획된 기능, 알려진 문제를 관리한다.

**이 문서는 매 작업 완료 시 반드시 갱신해야 한다.**

---

## 1. 현재 상태

**버전:** 0.2.0 (공개)

**최종 업데이트:** Phase 5-6 완료, PyPI 공개

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

---

## 3. 미구현 기능

### 추가 고려 사항

- [ ] 멀티모달 입력 지원 (이미지, 파일 등)
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
| 스트리밍은 OpenAI만 네이티브 | 낮음 | Anthropic, Google은 fallback (non-streaming 후 단일 이벤트) |

---

## 5. 변경 이력

### 0.2.0

- Phase 5 완료: 스트리밍, 로깅, 메시지 추적, 호출 트레이싱, 디버그 모드
- Phase 6 완료: GitHub repo, CI/CD, 61개 테스트, PyPI 배포
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
