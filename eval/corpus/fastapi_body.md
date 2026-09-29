# FastAPI 请求体：Pydantic 模型与 JSON 校验

## 用 BaseModel 声明请求体模型

POST 接口要接收 JSON 请求体时，先定义一个继承自 `BaseModel` 的类来描述字段和类型。FastAPI 会自动解析请求体里的 JSON：

```python
from pydantic import BaseModel
from fastapi import FastAPI

app = FastAPI()

class Item(BaseModel):
    name: str
    price: float
    is_offer: bool = False

@app.post("/items")
def create_item(item: Item):
    return {"收到的商品名": item.name, "价格": item.price}
```

这就是 POST 接收 JSON 的完整最小写法：定义 BaseModel 类，在路径函数里用类型注解声明该模型类型参数。

## 422 校验失败响应

如果客户端发来的 JSON 缺少必填字段（例如没给 price），或类型对不上（price 传了字符串 "十元"），Pydantic 校验失败，FastAPI 直接返回 422，响应中逐字段列出错误位置和原因，函数体完全不会执行。

默认值字段可以不传（上例 is_offer 默认 False）；嵌套对象、列表字段也用类型注解表达：`tags: list[str] = []`。

## 请求体与查询参数的区别

请求体（Body）是 POST/PUT 携带的 JSON 数据，适合提交结构化的、字段较多的数据；查询参数（Query）是 URL 问号后的键值对，适合简单的过滤分页。FastAPI 靠参数类型区分：BaseModel 子类被当成请求体，基本类型（str/int）被当成查询参数。

## Pydantic 是什么

Pydantic 是一个数据校验库，核心能力是按类型注解校验数据并自动转换：传 "42" 给 int 字段会转成整数 42，转不了才报错。FastAPI 深度集成 Pydantic，请求体、查询参数、响应模型的校验与 JSON Schema 文档生成都由它支撑。
