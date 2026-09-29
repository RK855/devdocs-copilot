# agent-body-json（API用法）

- 期望：agent；实际：agent；degraded：False
- 耗时：28.42s；调用 3 次 / 2 轮；失败步 0
- 缺失关键词：无

## 答案



## FastAPI POST 接收 JSON 请求体

### 核心原理

FastAPI 通过 **类型注解** 区分参数来源：
- **`BaseModel` 子类** → 请求体（Body），用于 POST/PUT 的 JSON 数据
- **基本类型（`str`/`int`/...）** → 查询参数（Query），用于 URL 问号后的键值对

---

### 最小示例

```python
from pydantic import BaseModel
from fastapi import FastAPI

app = FastAPI()

class Item(BaseModel):
    name: str
    price: float
    is_offer: bool = False  # 有默认值，可不传

@app.post("/items")
def create_item(item: Item):
    return {"商品名": item.name, "价格": item.price}
```

客户端请求示例：
```json
POST /items
Content-Type: application/json

{
  "name": "苹果",
  "price": 5.5,
  "is_offer": true
}
```

---

### 高级用法：嵌套对象与列表

```python
from pydantic import BaseModel
from fastapi import FastAPI

app = FastAPI()

class Address(BaseModel):
    street: str
    city: str

class Item(BaseModel):
    name: str
    price: float
    tags: list[str] = []          # 列表字段
    address: Address              # 嵌套对象

@app.post("/items")
def create_item(item: Item):
    return {"name": item.name, "city": item.address.city}
```

---

### 校验失败处理

当客户端发送的 JSON 缺少必填字段或类型不对时，Pydantic 会自动校验，FastAPI 直接返回 **422**，函数体不会执行。例如：

```bash
# 缺失 price 字段
curl -X POST http://localhost:8000/items \
  -H "Content-Type: application/json" \
  -d '{"name": "苹果"}'
```

响应：
```json
{
  "detail": [
    {
      "loc": ["body", "price"],
      "msg": "field required",
      "type": "missing"
    }
  ]
}
```

---

### 关键要点

| 写法 | 含义 |
|------|------|
| `field: str` | 必填字符串字段 |
| `field: str = "默认"` | 可选字段，不传时用默认值 |
| `field: list[str] = []` | 列表字段，避免 `None` |
| `field: NestedModel` | 嵌套对象，递归校验 |

## steps

```json
[
  {
    "step": 1,
    "tool": "search_docs",
    "arguments": {
      "query": "FastAPI POST 接收 JSON 请求体 request body",
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
      "query": "FastAPI Body Pydantic model POST endpoint",
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
      "task": "POST 接口接收 JSON 请求体，使用 Pydantic BaseModel 定义字段，包含必填字段、默认值字段、列表字段和嵌套对象示例"
    },
    "result_count": 0,
    "cached": false,
    "status": "ok",
    "error": null
  }
]
```
