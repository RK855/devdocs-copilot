# agent-path-validate（API用法）

- 期望：agent；实际：agent；degraded：False
- 耗时：7.96s；调用 2 次 / 1 轮；失败步 0
- 缺失关键词：无

## 答案



FastAPI 路径参数大于 0 的校验，使用 `Path()` 并传入 `gt=0`（greater than）参数即可：

```python
from fastapi import FastAPI, Path

app = FastAPI()

@app.get("/items/{item_id}")
def get_item(item_id: int = Path(..., gt=0, description="物品编号，必须为正整数")):
    return {"item_id": item_id}
```

## 说明

- `...`（Ellipsis）表示该参数**必填**
- `gt=0`：数值必须**严格大于** 0
- 其他常用校验参数：
  - `ge=0`：大于等于
  - `lt=100`：小于
  - `le=100`：小于等于

## 校验失败响应

当请求 `/items/0` 或 `/items/-1` 时，FastAPI 自动返回 **HTTP 422 Unprocessable Entity**，无需手写 if 判断：

```json
{
  "detail": [
    {
      "loc": ["path", "item_id"],
      "msg": "ensure this value is greater than 0",
      "type": "value_error.number.not_gte",
      "ctx": {"limit_value": 0}
    }
  ]
}
```

## steps

```json
[
  {
    "step": 1,
    "tool": "search_docs",
    "arguments": {
      "query": "FastAPI path parameter validation greater than 0",
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
      "query": "FastAPI 路径参数 整数 校验 大于",
      "top_k": 5
    },
    "result_count": 5,
    "cached": false,
    "status": "ok",
    "error": null
  }
]
```
