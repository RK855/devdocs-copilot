# FastAPI 依赖注入进阶

## Depends 的基本形态

FastAPI 的依赖注入通过 `Depends` 声明。依赖可以是一个函数、一个可调用对象，也可以是一个类。框架会在处理请求前解析依赖树，把返回值注入到路径操作函数的参数里。

```python
def common_params(q: str = "", skip: int = 0, limit: int = 10):
    return {"q": q, "skip": skip, "limit": limit}

@app.get("/items/")
async def read_items(params: dict = Depends(common_params)):
    return params
```

依赖可以继续依赖别的依赖，形成依赖树。FastAPI 会对同一个请求内的相同依赖做缓存，默认 `use_cache=True`，避免重复执行。

## 类依赖与可调用对象

类也可以作为依赖。类依赖的优势是能把参数组合成一个有行为的对象，同时利用 `__init__` 签名做参数校验。

```python
class Pagination:
    def __init__(self, skip: int = 0, limit: int = 10):
        self.skip = skip
        self.limit = limit

@app.get("/users/")
async def list_users(p: Pagination = Depends()):
    return {"skip": p.skip, "limit": p.limit}
```

注意写成 `Depends()` 而不是 `Depends(Pagination)` 也能工作，FastAPI 会从类型注解推断。

## 带 yield 的依赖

生成器依赖适合管理请求级资源，例如数据库会话、临时文件、锁。`yield` 之前的代码在请求处理前执行，之后的代码在响应发送后执行，即使抛出异常也会执行清理逻辑。

```python
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

带 yield 的依赖只能 yield 一次；如果依赖内部抛出异常，可以在依赖里捕获后转成 `HTTPException`。清理代码抛出的异常会向上传播，影响响应。

## 全局依赖与路由级依赖

`FastAPI(dependencies=[Depends(verify_token)])` 让依赖作用于整个应用；`APIRouter(dependencies=[...])` 作用于该路由组；路径操作装饰器的 `dependencies=[...]` 只作用于单个接口。这些依赖的返回值不会注入到参数，只用于副作用，例如鉴权、限流、审计。

依赖的执行顺序是：应用级 → 路由级 → 装饰器级 → 函数参数依赖。同级之间按声明顺序执行。

## 依赖覆盖与测试

`app.dependency_overrides` 可以在测试中把真实依赖替换成假对象，这是 FastAPI 官方推荐的测试方式。

```python
def fake_db():
    return FakeSession()

app.dependency_overrides[get_db] = fake_db
```

覆盖字典是全局的，测试结束后要清空 `app.dependency_overrides.clear()`，否则会污染后续用例。相比 monkeypatch 模块属性，依赖覆盖只影响被覆盖的那一条依赖链，粒度更准。

## 依赖注入的边界

依赖适合做“请求上下文相关”的事情：解析请求头、校验令牌、打开数据库会话、读取配置。不适合放重业务逻辑，因为依赖会在每次请求重复执行，且难以单独做单元测试。复杂业务流程应该放在 service 层，依赖只负责把依赖对象组装好传进去。这样 service 可以脱离 HTTP 框架单独测试。
