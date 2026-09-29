# agent-code-health（代码生成）

- 期望：agent；实际：agent；degraded：False
- 耗时：24.26s；调用 2 次 / 2 轮；失败步 0
- 缺失关键词：无

## 答案



## 最小可运行示例

**`main.py`**

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
def health_check():
    """健康检查接口，返回服务运行状态"""
    return {"status": "healthy"}
```

**启动**

```bash
uvicorn main:app
```

默认监听 `http://127.0.0.1:8000`，访问 `/health` 即可验证：

```bash
curl http://127.0.0.1:8000/health
# {"status":"healthy"}
```

**补充说明**

- `@app.get("/health")` 声明路径，FastAPI 会自动将 GET 请求映射到该函数并序列化为 JSON 响应
- 开发时可用 `uvicorn main:app --reload` 开启热重载
- 交互式 API 文档地址：`http://127.0.0.1:8000/docs`

## steps

```json
[
  {
    "step": 1,
    "tool": "search_docs",
    "arguments": {
      "query": "FastAPI 健康检查 health endpoint 示例",
      "top_k": 5
    },
    "result_count": 5,
    "cached": false,
    "status": "ok",
    "error": null
  },
  {
    "step": 2,
    "tool": "generate_code_example",
    "arguments": {
      "task": "写一个带 /health 健康检查接口的最小可运行 FastAPI 示例"
    },
    "result_count": 0,
    "cached": false,
    "status": "ok",
    "error": null
  }
]
```
