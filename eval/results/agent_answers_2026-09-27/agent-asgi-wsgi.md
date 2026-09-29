# agent-asgi-wsgi（概念）

- 期望：agent；实际：agent；degraded：False
- 耗时：39.48s；调用 4 次 / 2 轮；失败步 0
- 缺失关键词：无

## 答案



## ASGI vs WSGI 区别

两者都是 Python Web 应用的**接口规范**（Application Server Gateway Interface），定义了 Web 服务器如何与 Web 框架通信。

| 维度 | WSGI | ASGI |
|------|------|------|
| **全称** | Web Server Gateway Interface | Asynchronous Server Gateway Interface |
| **模型** | 同步，单线程处理一个请求 | 异步，基于事件循环，可并发处理大量连接 |
| **协议函数签名** | `def application(environ, start_response)` | `async def application(scope, receive, send)` |
| **长连接 / WebSocket** | ❌ 不支持 | ✅ 原生支持 |
| **典型服务器** | gunicorn、uWSGI | uvicorn、hypercorn |
| **典型框架** | Flask、Django（同步视图） | FastAPI、Starlette、Django（异步视图） |
| **适用场景** | 普通 CRUD 业务，请求-响应简单 | 高并发 I/O、流式响应、实时推送、WebSocket |

### 核心差异说明

**1. 调用方式不同**
- WSGI：服务器调用应用函数，传入 `environ`（请求上下文 dict）和 `start_response`（回调，用于设置响应头）
- ASGI：应用是 `async def` 协程，通过 `scope`（请求描述 dict）、`receive`（收消息）和 `send`（发消息）进行双向通信

**2. 并发模型**
- WSGI：一个请求一个线程/进程，阻塞式等待 I/O
- ASGI：单线程事件循环，遇到 `await` I/O 时让出执行权，同一线程可服务多个连接

**3. 生态选择**
- 只做传统 Web 服务 → WSGI 框架足够
- 需要 WebSocket、SSE 或高并发 → 选 ASGI（如 FastAPI）

> ⚠️ 注意：ASGI 的 `async def` 视图里不能直接调用阻塞库（如同步 HTTP 客户端），否则会卡死事件循环；应改用异步库或将阻塞操作放到线程池中执行。

## steps

```json
[
  {
    "step": 1,
    "tool": "search_docs",
    "arguments": {
      "query": "ASGI WSGI 区别",
      "top_k": 5
    },
    "result_count": 5,
    "cached": false,
    "status": "ok",
    "error": null
  },
  {
    "step": 1,
    "tool": "search_docs",
    "arguments": {
      "query": "ASGI WSGI protocol Python web",
      "top_k": 5
    },
    "result_count": 5,
    "cached": false,
    "status": "ok",
    "error": null
  },
  {
    "step": 2,
    "tool": "search_docs",
    "arguments": {
      "query": "ASGI callable protocol scope messages",
      "top_k": 3
    },
    "result_count": 3,
    "cached": false,
    "status": "ok",
    "error": null
  },
  {
    "step": 2,
    "tool": "search_docs",
    "arguments": {
      "query": "WSGI environ start_response",
      "top_k": 3
    },
    "result_count": 3,
    "cached": false,
    "status": "ok",
    "error": null
  }
]
```
