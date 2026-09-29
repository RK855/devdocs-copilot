# agent-422（报错分析）

- 期望：agent；实际：agent；degraded：False
- 耗时：19.92s；调用 2 次 / 1 轮；失败步 0
- 缺失关键词：无

## 答案



## FastAPI 返回 422 的含义

**HTTP 422 Unprocessable Entity** 表示请求格式正确，但**内容无法处理**。在 FastAPI 中，这几乎总是由 **Pydantic 校验失败**导致。

### 常见触发场景

| 场景 | 示例 |
|------|------|
| 缺少必填字段 | 请求体没传 `price`，但模型声明 `price: float` |
| 类型不匹配 | `int` 参数传了字符串 `"abc"`，或 `float` 传了 `"十元"` |
| 路径参数类型错误 | `/items/abc` 但路由声明 `item_id: int` |
| 校验规则不满足 | 用了 `Field(min_value=1)` 但传了 0 |
| 请求体格式问题 | Content-Type 不是 `application/json`，或 JSON 语法错误 |

### 如何排查

1. **看响应体** — FastAPI 会返回详细的错误信息，包含字段名和原因：
   ```json
   {
     "detail": [
       {
         "loc": ["body", "price"],
         "msg": "value is not a valid float",
         "type": "type_error.float"
       }
     ]
   }
   ```
   - `loc` 指出错误位置（`body` 表示请求体，`path` 表示路径参数等）
   - `msg` 是具体错误描述
   - `type` 是错误类型

2. **检查请求参数** — 对比接口文档，确认：
   - 必填字段是否都传了
   - 类型是否正确（特别注意 `int` vs `str`、`bool` 的值格式）
   - Content-Type 是否设置正确

3. **本地复现** — 用 Postman 或 curl 直接调用，观察响应

### 示例：类型不匹配导致 422

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/items/{item_id}")
def get_item(item_id: int):
    return {"item_id": item_id}
```

访问 `/items/abc` 会返回：
```json
{
  "detail": [
    {
      "loc": ["path", "item_id"],
      "msg": "value is not a valid integer",
      "type": "type_error.integer"
    }
  ]
}
```

### 总结

- **422 = 客户端传的数据不符合接口定义**
- 先看响应体的 `detail` 数组，里面有精确的错误定位
- 根据 `loc` 判断是路径参数、查询参数还是请求体出错，再修正客户端请求

## steps

```json
[
  {
    "step": 1,
    "tool": "search_docs",
    "arguments": {
      "query": "FastAPI 422 Unprocessable Entity 错误排查",
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
      "query": "FastAPI validation error response model",
      "top_k": 5
    },
    "result_count": 5,
    "cached": false,
    "status": "ok",
    "error": null
  }
]
```
