# Agent List Isolation — 에이전트 리스트 격리

이 문서는 `run()`/`async_run()`에 전달되는 `agents` 리스트의作用域과 팀 격리 메커니즘을 설명한다.

---

## 1. 개요: agents 리스트 = 팀 경계

`run()` 호출 시 전달하는 `agents` 리스트가 곧 해당 실행의 팀 경계를 정의한다.

```python
result = run(
    entry=researcher,
    agents=[researcher, writer, reviewer],  # ← 이 세 에이전트만互相認知
    tools=[search_web],
    providers=[openai],
)
```

이 실행 내에서:
- `researcher`는 `writer`와 `reviewer`를 알고 있고 호출할 수 있다.
- `writer`는 `researcher`와 `reviewer`를 알고 있고 호출할 수 있다.
- **세 에이전트 외의 존재는 알 수 없다.**

---

## 2. 철학과의 관계: 부를 자유 vs. 全원 видимость

핵심 철학은 **"에이전트A가 에이전트B를 부르려 할 때 시스템이 막지 않는다"** 이다.

이것과 **"모든 에이전트가 全원 existence를 알고 있다"**는 같은 것이 아니다:

| 구분 | 설명 |
|------|------|
| **부를 자유** | 시스템이 `call_agent`를阻挡하지 않음 |
| **全域 видимость** | 모든 에이전트가 全원 이름과 instructions를 시스템 프롬프트에서 확인 |

철학은前者을意味し、後者를意味하지 않는다. 에이전트 리스트 외부에 있는 에이전트를 "부르려 해도 알 수 없으므로 부를 수 없는 것"은 restriction이 아니라 単純な ignorance이다.

---

## 3. 격리 수준

### 수준 1: 같은 프로세스, 다른 run() 호출

각 `run()`/`async_run()`은 독립적인 `Router`와 `Runtime` 인스턴스를 생성한다.

```python
# team_a.py
result_a = run(
    entry=a1,
    agents=[a1, a2],  # a1은 a2만 알고, b1/b2의 존재를 모름
    ...
)

# team_b.py (별도 파일, 같은 프로세스)
result_b = run(
    entry=b1,
    agents=[b1, b2],  # b1은 b2만 알고, a1/a2의 존재를 모름
    ...
)
```

두 호출은 프로세스 안에서 동시에 실행也可能하지만, 서로의 agents 리스트를 알지 못하므로 호출도 불가능하다.

### 수준 2: 별도 프로세스

별도 프로세스로 실행하면 메모리 자체가 분리되므로 완전한 격리가 보장된다.

```python
# main.py
import multiprocessing

def run_team_a():
    from agentouto import run, Agent, Provider
    # team_a agents만 정의
    ...

def run_team_b():
    from agentouto import run, Agent, Provider
    # team_b agents만 정의
    ...

if __name__ == "__main__":
    p1 = multiprocessing.Process(target=run_team_a)
    p2 = multiprocessing.Process(target=run_team_b)
    p1.start()
    p2.start()
```

별도 프로세스인 경우 `AgentLoopRegistry` 싱글톤도 프로세스별로 분리되므로 완전히 독립적이다.

---

## 4. 시스템 프롬프트와 agents 리스트

Router가 생성하는 시스템 프롬프트에는 **현재 Router에 등록된 agents만** 포함된다.

```
You are "researcher". Research expert.

Available agents:
- writer: Skilled writer. Turn research into polished reports.
- reviewer: Critical reviewer. Verify facts and improve quality.
```

이 목록은 `run()` 호출 시 전달한 `agents` 리스트에서 현재 에이전트를 제외한 나머지로 구성된다. 따라서:

- `agents=[a1, a2, b1, b2]`로 호출하면 → a1에게 다른 3개 agents 모두 보임
- `agents=[a1, a2]`로 호출하면 → a1에게 a2만 보임, b1/b2는 존재 자체가 언급 안 됨

---

## 5. call_agent의 동작과 agents 리스트

LLM이 `call_agent(agent_name="...", message="...")`를 호출하면:

1. Runtime이 `self._router.get_agent(agent_name)` 호출
2. Router가 `self._agents` 딕셔너리에서 해당 에이전트를 조회
3. **존재하지 않으면 `RoutingError` 발생**

```python
def _resolve_agent_target(self, agent_name: str) -> Agent:
    if agent_name not in self._router.agent_names:
        available = ", ".join(self._router.agent_names) or "(none)"
        raise RoutingError(
            f"Unknown agent: '{agent_name}'. Available agents: {available}"
        )
    return self._router.get_agent(agent_name)
```

에이전트 리스트 외부에 있는 에이전트를 호출하려 하면 즉시 에러가 발생한다. 이것은 시스템의tructural restriction이며, 철학적 restriction이 아니다.

---

## 6. 라이브러리에서 사용할 때

라이브러리가 agentouto를 사용하여 에이전트 팀을 제공하더라도, 그 라이브러리를 import하는 코드와 agents 리스트가 공유되지 않는다.

```python
# mylib/agent_team.py
from agentouto import Agent, Provider, run

class MyAgentLibrary:
    def __init__(self):
        self.provider = Provider(name="openai", kind="openai", api_key="...")
        self.agent = Agent(name="lib_agent", instructions="...", model="gpt-4o", provider="openai")
    
    def run_task(self, message: str):
        # 이 Router에는 lib_agent만 존재
        return run(entry=self.agent, agents=[self.agent], ...)
```

```python
# main.py
from mylib.agent_library import MyAgentLibrary
from agentouto import Agent, Provider, run

lib = MyAgentLibrary()
lib.run_task("...")  # main의 agents와 격리됨

# main의 독립적인 agents 리스트
main_provider = Provider(name="anthropic", kind="anthropic", api_key="...")
main_agent = Agent(name="main", instructions="...", model="claude-sonnet-4-6", provider="anthropic")
result = run(entry=main_agent, agents=[main_agent], ...)  # lib_agent와 완전 격리
```

라이브러리의 `run()`과 메인 코드의 `run()`은:
- 각자의 `Router` 인스턴스 보유
- 각자의 `agents` 딕셔너리 보유
- 서로의 에이전트를 알지 못함

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

같은 이름의 에이전트를 하나의 `agents` 리스트에 포함하면:

```python
run(entry=a1, agents=[a1, a2, b1, b2], ...)
# Router._agents = {"coordinator": ???, "worker": ..., "reviewer": ...}
# "coordinator"는 마지막에 추가된 b1으로 덮어씌워짐
```

**에러가 발생하지 않고** 조용히 마지막 에이전트로取代される. 이름 충돌을 방지하려면:
- 팀마다 고유한 에이전트 이름 사용
- 또는 별도 프로세스로 격리

---

## 8. 요약표

| 방법 | 팀 격리 | 구현 난이도 | 주의사항 |
|------|---------|------------|----------|
| 같은 `run()`, agents 병합 | ❌ 전원visibility | 가장 쉬움 | 이름 충돌 가능 |
| 같은 프로세스, 다른 `run()` | ✅ 각 Router 독립 | 쉬움 | 이름 충돌 주의 |
| 별도 프로세스 | ✅ 완전 격리 | 중간 | 프로세스 간 통신 별도 구현 필요 |
| 별도 머신/서비스 | ✅ 완전 격리 | 높음 | IPC 메커니즘 필요 |

**추천:**
- 개발 초기나 소규모: 같은 프로세스에서 팀별 `run()` 호출
- 프로덕션에서 완전한 격리 필요: 별도 프로세스 또는 마이크로서비스 아키텍처
