# FastAPI 中间件与 CORS

## 中间件的执行模型

中间件是包裹整个 ASGI 应用的一层函数，请求进来先经过中间件，响应出去再反向经过中间件。FastAPI 基于 Starlette，使用 `@app.middleware("http")` 装饰器注册函数式中间件。

```python
@app.middleware("http")
async def add_process_time(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Process-Time"] = f"{time.perf_counter() - start:.4f}"
    return response
```

多个中间件按注册顺序形成洋葱结构：先注册的在最外层，请求阶段最先执行、响应阶段最后执行。中间件里不要做阻塞 IO，否则会卡住事件循环。

## 中间件与依赖的区别

中间件对所有请求生效，拿不到路径参数和 Pydantic 模型，适合横切关注点：请求日志、耗时统计、请求 ID、全局异常兜底、压缩、CORS。依赖更贴近具体接口，能拿到类型化的参数，适合鉴权和资源准备。

一个常见误区是把业务鉴权全塞进中间件，结果每个接口都要在中间件里判断路径白名单，既脆弱又难测。更好的做法是鉴权用依赖，中间件只做通用观测。

## CORS 是什么

CORS（跨源资源共享）是浏览器实施的安全策略。当页面来源（协议 + 域名 + 端口）与请求目标不一致时，浏览器会拦截响应，除非服务端明确允许。注意 CORS 是浏览器行为，服务端之间的调用不受影响。

简单请求会直接发出，服务端返回 `Access-Control-Allow-Origin`；非简单请求（例如带自定义头、PUT/DELETE、JSON 以外的 Content-Type）会先发 `OPTIONS` 预检请求，服务端需要正确响应预检，浏览器才会发真实请求。

## CORSMiddleware 配置

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

`allow_origins=["*"]` 表示允许任意来源，但与 `allow_credentials=True` 组合时浏览器会拒绝，因为规范禁止通配符携带凭证。需要携带 Cookie 时必须写成具体源列表。

`allow_credentials=True` 只代表允许浏览器发送凭证，服务端仍要自己校验会话。预检结果可以用 `max_age` 缓存，减少 OPTIONS 请求次数。

## 中间件顺序陷阱

`add_middleware` 的注册顺序与执行顺序相反：最后添加的在最外层。CORS 中间件通常要放在最外层，否则错误响应可能缺少 CORS 头，浏览器把真实错误显示成 CORS 错误，排查时非常误导。

## 请求 ID 与日志关联

生产环境常用请求 ID 中间件，为每个请求生成 UUID 并写入上下文变量，日志里带上它就能串起一次请求的所有日志。实现时可以用 `contextvars.ContextVar`，因为异步任务的上下文在 asyncio 中会被正确传递。

## 异常处理与中间件

中间件里 `call_next` 抛出异常时，默认会变成 500。可以捕获后返回结构化 JSON，但更推荐用 `app.exception_handler` 注册异常处理器，它只处理路由层抛出的异常，语义更清晰。纯 ASGI 中间件无法拿到已经开始的流式响应，流式接口的异常要在生成器内部处理。
