# pytest 异步测试与替身

## pytest-asyncio

异步测试需要 `pytest-asyncio` 插件。`asyncio_mode = auto` 让所有 `async def test_` 自动被识别，无需逐个加 `@pytest.mark.asyncio`。

```python
async def test_retrieve_async():
    result = await retrieve("问题", mode="vector", vector_store=store)
    assert result.hits
```

每个测试默认有独立的事件循环，fixture 如果是异步的，也要用 `@pytest.fixture` 配合 async def（auto 模式下可用）。

## Fake 与 Mock 的选择

优先用手写 Fake：行为可控、可读性好、不依赖 mock 框架的内部细节。Mock 适合断言“是否被调用、调用几次、参数是什么”。

```python
class FakeLLM:
    def __init__(self, answer="ok"):
        self.answer = answer
        self.calls = []

    def generate(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self.answer
```

Fake 记录调用，测试可以断言 `len(fake.calls) == 2`。这比 `mock.assert_called_once_with` 更直观，也不会因为重构内部调用顺序而碎掉。

## 不要在测试里断言实现细节

断言“调用了某个私有方法”会让重构立刻失败，即使外部行为没变。应该断言可观察结果：返回值、状态码、事件序列、写入的数据。测试应该描述“做什么”，而不是“怎么做”。

## HTTP 层替身

测试 FastAPI 用 `TestClient`，同步接口直接调用；异步场景可用 `httpx.AsyncClient` 配合 ASGITransport。外部 HTTP 依赖用 `httpx.MockTransport` 拦截请求，返回构造好的响应，避免真实网络。

```python
def handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"ok": True})
```

## 时间与随机

依赖时间的功能用可注入的时钟或 monkeypatch，避免 sleep 拖慢测试。随机行为要固定种子，或者把随机数生成器作为依赖注入。

## 并发测试

异步并发可以用 `asyncio.gather` 同时发起多个请求，断言全部完成、无死锁。要注意 Fake 是否线程安全，异步 Fake 用 `asyncio.sleep(0)` 模拟让出。

## 覆盖率

pytest-cov 生成覆盖率报告：

```bash
pytest --cov=app --cov-report=term-missing
```

覆盖率是下限指标，不是目标。100% 覆盖也可能没有断言真实行为，60% 覆盖也可能抓住了核心风险。看 `missing` 行比看百分比更有价值。

## 测试速度

单测应在秒级完成。真实 API、真实数据库、大文件解析要打标记并默认跳过，由环境变量或命令行开关控制。慢测试会让人不愿运行，最终形同虚设。
