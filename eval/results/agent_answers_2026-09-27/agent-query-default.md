# agent-query-default（API用法）

- 期望：agent；实际：agent；degraded：False
- 耗时：8.47s；调用 2 次 / 1 轮；失败步 0
- 缺失关键词：无

## 答案



## FastAPI 查询参数设置默认值

在 FastAPI 中，查询参数通过 `Query()` 声明，**赋予默认值即可让参数变为可选**。

### 基本用法

```python
from fastapi import FastAPI, Query

app = FastAPI()

@app.get("/search")
def search(
    q: str = Query(default="", max_length=20),
    page: int = Query(default=1, ge=1)
):
    return {"q": q, "page": page}
```

- 不传 `q` 时，默认取 `""`；不传 `page` 时，默认取 `1`
- 访问 `/search?q=python&page=2` → `{"q": "python", "page": 2}`
- 访问 `/search` → `{"q": "", "page": 1}`

### 关键要点

| 写法 | 含义 |
|------|------|
| `Query(default=...)` | 可选参数，有默认值 |
| `Query(...)` 或 `Query(default=...)` 但省略 default | 必填参数，缺省时返回 422 |
| `Query(default=..., ge=1, max_length=20)` | 可选 + 校验规则 |

### 注意事项

- **类型注解必须保留**：`q: str = Query(...)` — 不能写成 `q = Query(...)`，否则 FastAPI 无法识别为查询参数
- **校验与默认值可同时使用**：如 `ge=1`（大于等于）、`max_length=20`、`regex=...`
- 缺少必填参数或传入非法值时，FastAPI 自动返回 **HTTP 422**，无需手写校验逻辑

## steps

```json
[
  {
    "step": 1,
    "tool": "search_docs",
    "arguments": {
      "query": "FastAPI 查询参数 默认值 Query",
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
      "query": "FastAPI query parameters default value",
      "top_k": 5
    },
    "result_count": 5,
    "cached": false,
    "status": "ok",
    "error": null
  }
]
```
