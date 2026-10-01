# Agent List Isolation — 에이전트 리스트 격리

이 문서는 `run()`/`async_run()`에 전달되는 `starting_agents`와 `run_agents`의 의미와 팀 격리 메커니즘을 설명한다.

---

## 1. 핵심 개념

### `starting_agents` — 시작 에이전트

동시에 시작하는 **동등한 에이전트들**. 순서에 의미 없음.

```python
run(
    starting_agents=[a, b, c],  # a, b, c 모두 동등! 동시에 시작
    ...
)
```

### `run_agents` — 참여자 풀

이 run에 **참여하는 에이전트들**.

- `run_agents` 미지정 → `starting_agents`와 동일 (기본값)
- `run_agents` 지정 → 해당 에이전트들만 참여

**중요:** `starting_agents`에 있지만 `run_agents`에 **없는** 에이전트는:
- 실행은 되지만 (자체 루프에서 동작)
- 다른 에이전트를 호출할 수 없음
- 다른 에이전트에게 인식되지 않음
- **경고(WARNING)가 발행됨**

---

## 2. 올바른 사용 vs. 잘못된 사용

### ✅ Good: 모든 참여자가 run_agents에 포함

```python
run(
    starting_agents=[researcher, writer, reviewer],
    run_agents=[researcher, writer, reviewer],  # 모두 참여
    ...
)
# 세 에이전트 모두:
# - 병렬로 실행됨
# - 서로를 호출 가능
# - 서로를 인식
```

### ❌ Bad: 일부만 참여자로 포함

```python
run(
    starting_agents=[researcher, writer, reviewer],
    run_agents=[researcher, writer],  # reviewer는 참여자가 아님!
    ...
)
# 경고発行! reviewer는:
# - 실행 안 됨
# - 호출 안 됨
# - 인식 안 됨
```

이 패턴은 **권장하지 않음**. 경고가発行되며, 예상치 못한 동작을 유발할 수 있음.

---

## 3. 격리 수준

### 수준 1: 같은 프로세스, 다른 run() 호출

각 `run()`/`async_run()`은 독립적인 `Router`와 `Runtime` 인스턴스를 생성한다.

```python
# team_a.py
result_a = run(
    starting_agents=[a1, a2],
    run_agents=[a1, a2],  # a1, a2만 서로를 인식
    ...
)

# team_b.py (별도 파일, 같은 프로세스)
result_b = run(
    starting_agents=[b1, b2],
    run_agents=[b1, b2],  # b1, b2만 서로를 인식
    ...
)
```

### 수준 2: 별도 프로세스

별도 프로세스로 실행하면 메모리 자체가 분리되므로 완전한 격리가 보장된다.

```python
# main.py
import multiprocessing

def run_team_a():
    from agentouto import run, Agent, Provider
    ...

def run_team_b():
    from agentouto import run, Agent, Provider
    ...

if __name__ == "__main__":
    p1 = multiprocessing.Process(target=run_team_a)
    p2 = multiprocessing.Process(target=run_team_b)
    p1.start()
    p2.start()
```

---

## 4. 시스템 프롬프트와 run_agents

Router가 생성하는 시스템 프롬프트에는 **run_agents에 등록된 에이전트만** 포함된다.

```
You are "researcher". Research expert.

Available agents:
- writer: Skilled writer. Turn research into polished reports.
- reviewer: Critical reviewer. Verify facts and improve quality.
```

---

## 5. call_agent의 동작과 run_agents

LLM이 `call_agent(agent_name="...", message="...")`를 호출하면:

1. `agentouto/_bridge/tools.py`의 `resolve_agent_target(agent_name)` 호출
2. Router가 `self._agents` 딕셔너리에서 해당 에이전트를 조회
3. **존재하지 않으면 `RoutingError` 발생**

```python
def resolve_agent_target(router: Router, agent_name: str) -> Agent:
    if agent_name not in router.agent_names:
        available = ", ".join(router.agent_names) or "(none)"
        raise RoutingError(
            f"Unknown agent: '{agent_name}'. Available agents: {available}"
        )
    return router.get_agent(agent_name)
```

---

## 6. 라이브러리에서 사용할 때

라이브러리가 agentouto를 사용하여 에이전트 팀을 제공하더라도, 그 라이브러리를 import하는 코드와 run_agents가 공유되지 않는다.

```python
# mylib/agent_team.py
class MyAgentLibrary:
    def run_task(self, message: str):
        return run(starting_agents=[self.agent], run_agents=[self.agent], ...)
```

```python
# main.py
lib = MyAgentLibrary()
lib.run_task("...")  # main의 run_agents와 격리됨
```

---

## 7. 주의사항: 이름 충돌

같은 프로세스에서 여러 에이전트 팀을 사용할 때 **이름 충돌**에 주의해야 한다.

```python
# 팀 A
a1 = Agent(name="coordinator", ...)
a2 = Agent(name="worker", ...)

# 팀 B
b1 = Agent(name="coordinator", ...)  # 이름 충돌!
b2 = Agent(name="reviewer", ...)
```

같은 이름의 에이전트를 하나의 `run_agents`에 포함하면 마지막 것으로 덮어씌워진다.

---

## 8. 요약표

| 방법 | 팀 격리 | 구현 난이도 | 주의사항 |
|------|---------|------------|----------|
| 같은 `run()`, run_agents 병합 | ❌ 전원visibility | 가장 쉬움 | 이름 충돌 가능 |
| 같은 프로세스, 다른 `run()` | ✅ 각 Router 독립 | 쉬움 | 이름 충돌 주의 |
| 별도 프로세스 | ✅ 완전 격리 | 중간 | 프로세스 간 통신 별도 구현 필요 |
| 별도 머신/서비스 | ✅ 완전 격리 | 높음 | IPC 메커니즘 필요 |

**추천:**
- 개발 초기나 소규모: 같은 프로세스에서 팀별 `run()` 호출
- 프로덕션에서 완전한 격리 필요: 별도 프로세스 또는 마이크로서비스 아키텍처
