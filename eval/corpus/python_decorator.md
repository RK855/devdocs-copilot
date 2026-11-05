# Python 装饰器

## 基本形态

装饰器是接收函数并返回新函数的可调用对象。`@decorator` 等价于 `func = decorator(func)`。常见用途：日志、计时、重试、缓存、鉴权、参数校验。

```python
def logged(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        print(f"call {fn.__name__}")
        return fn(*args, **kwargs)
    return wrapper
```

`functools.wraps` 保留原函数的名称、文档字符串与签名信息，缺少它会让调试与文档生成失真。

## 带参数的装饰器

带参数的装饰器是三层结构：最外层接收参数，返回真正的装饰器。

```python
def retry(times=2):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            for i in range(times):
                try:
                    return fn(*args, **kwargs)
                except Exception:
                    if i == times - 1:
                        raise
        return wrapper
    return decorator
```

调用方式 `@retry(times=3)`。忘记最外层调用会得到错误类型。

## 类装饰器

类也可以作为装饰器，实现 `__call__`。适合需要保存状态的装饰器，例如计数器。类装饰器在实例化时保存配置，在调用时执行逻辑。

## 异步函数装饰器

装饰异步函数时，wrapper 也必须是 async，否则返回的是协程对象而不是结果。

```python
def timed(fn):
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            return await fn(*args, **kwargs)
        finally:
            print(f"{fn.__name__} {time.perf_counter() - start:.3f}s")
    return wrapper
```

## 装饰器顺序

多个装饰器从下往上应用：

```python
@a
@b
def f(): ...
```

等价于 `f = a(b(f))`。顺序会影响行为，例如鉴权应在外层，缓存应在内层，否则未授权请求也可能命中缓存。

## 常见用途

- 路由注册：FastAPI 的 `@app.get` 本质是装饰器
- 依赖注入：`@inject`
- 缓存：`functools.lru_cache`
- 重试：配合退避策略
- 权限校验：检查当前用户角色

## 常见坑

- 忘记 `functools.wraps`，丢失元信息
- 异步函数用了同步 wrapper
- 装饰器顺序搞反
- 在装饰器里捕获异常却不记录
- 装饰器修改函数签名导致框架无法解析参数
