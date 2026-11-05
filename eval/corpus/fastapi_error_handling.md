# FastAPI 错误处理

## HTTPException

业务代码抛出 `HTTPException(status_code=..., detail=...)` 时，FastAPI 会终止请求并返回 JSON：`{"detail": "..."}`。`detail` 可以是字符串，也可以是列表或字典，前端需要按约定解析。

```python
from fastapi import HTTPException

@app.get("/items/{item_id}")
async def read_item(item_id: int):
    if item_id not in items:
        raise HTTPException(status_code=404, detail="Item not found")
    return items[item_id]
```

抛出异常后，同一函数内后续代码不会执行，所以校验应放在函数开头。依赖里抛出的 HTTPException 同样会终止请求。

## 422 校验错误

当请求参数或请求体不符合 Pydantic 模型时，FastAPI 返回 422 Unprocessable Entity，响应体里 `detail` 是一个列表，每项包含 `loc`（出错位置）、`msg`（错误描述）、`type`（错误类型）。常见原因：

- 必填字段缺失
- 类型不匹配，例如把字符串传给整型字段
- 超出约束，例如 `gt=0` 收到 0
- JSON 语法错误，此时 `type` 为 `json_invalid`

排查时先看 `loc` 定位字段，再看 `msg`。前端如果直接把 `detail` 当字符串渲染，会显示成 `[object Object]`，需要判断类型分支处理。

## 自定义异常处理器

对于领域异常，推荐定义自己的异常类，再用 `exception_handler` 统一转成响应，避免 service 层依赖 HTTP 概念。

```python
class DocumentNotFound(Exception):
    pass

@app.exception_handler(DocumentNotFound)
async def handle_not_found(request, exc):
    return JSONResponse(status_code=404, content={"detail": str(exc)})
```

这样 service 层只抛领域异常，路由层或全局处理器负责映射状态码。测试时可以直接断言 service 抛出领域异常，不需要构造 HTTP 客户端。

## 请求校验错误的自定义

`RequestValidationError` 可以覆盖默认的 422 响应格式，例如把错误列表压平成一条人类可读的消息。注意覆盖后仍应保留字段定位信息，否则前端无法高亮具体输入框。

## 500 与业务错误

未捕获异常会变成 500 Internal Server Error，响应体通常只有一句 `Internal Server Error`，堆栈只出现在服务端日志。不要把可预期的业务失败当成 500，例如“文档不存在”应是 404，“参数冲突”应是 409，“上游模型不可用”应是 502 或 503。

有些团队为了前端统一处理，把所有错误都返回 HTTP 200，再用响应体里的状态字段区分。这种做法的代价是监控和网关无法按状态码统计错误率，也破坏了 HTTP 语义。更稳妥的是保留正确状态码，前端按状态码分支。

## 流式接口的错误

SSE 或流式响应一旦开始发送，状态码已经确定，无法再改成 500。此时只能在事件流里发送自定义 error 事件，让前端识别并停止渲染。因此流式链路要在第一个字节发出前完成所有可能失败的准备：鉴权、参数校验、检索、模型首包。首包之后的故障只能作为流内错误上报。

## 日志与错误的分层

错误发生时记录日志要注意级别：客户端参数错误用 INFO 或 WARNING，服务端故障用 ERROR，并带上请求 ID 与关键参数。不要把异常堆栈打印到响应里，既泄露实现细节也不专业。日志中避免记录完整请求体，可能包含密钥或个人信息。
