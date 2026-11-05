# Python 上下文管理器

## with 语句的语义

上下文管理器负责资源的获取与释放，`with` 保证退出时一定执行清理，即使发生异常。文件、锁、数据库连接、临时目录都适合用上下文管理器。

```python
with open("a.txt", encoding="utf-8") as f:
    data = f.read()
```

等价于 try/finally，但更简洁，也不容易忘记关闭。

## 类实现协议

实现 `__enter__` 与 `__exit__` 即可成为上下文管理器。`__exit__` 接收异常类型、异常值、堆栈，返回 True 表示吞掉异常，返回 False 或 None 表示继续抛出。

```python
class Timer:
    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.elapsed = time.perf_counter() - self.start
        return False
```

`__enter__` 的返回值会绑定到 `as` 后的变量。返回 self 常见于需要后续访问状态的场景。

## contextlib 工具

`@contextmanager` 装饰生成器函数，yield 前是进入逻辑，yield 后是退出逻辑。代码更短，但只能 yield 一次。

```python
from contextlib import contextmanager

@contextmanager
def temporary_env(key, value):
    old = os.environ.get(key)
    os.environ[key] = value
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old
```

`contextlib.ExitStack` 可以动态管理多个资源，适合数量不定的清理逻辑。`contextlib.suppress` 忽略指定异常。

## 异步上下文管理器

异步场景实现 `__aenter__` 与 `__aexit__`，或用 `@asynccontextmanager`。FastAPI 的 lifespan 就是异步上下文管理器，在应用启动时建资源、关闭时释放。

```python
@asynccontextmanager
async def lifespan(app):
    app.state.pool = await create_pool()
    yield
    await app.state.pool.close()
```

## 资源释放顺序

多个 with 可以写在一行，退出时按相反顺序释放，类似栈。嵌套结构要保证内层先释放，避免外层先关导致内层写入失败。

## 异常处理原则

上下文管理器不应吞掉未知异常。只有明确需要忽略的情况才返回 True，且要记录日志。吞异常会让问题静默，是最难排查的故障之一。

## 常见坑

- 用 try/finally 却忘了在 finally 里关闭
- `__exit__` 返回 True 吞掉异常
- 生成器上下文管理器忘记 try/finally
- 在异步函数里使用同步上下文管理器阻塞事件循环
- 资源在 with 外继续使用，已关闭
