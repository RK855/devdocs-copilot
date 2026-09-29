# FastAPI 路由：路径装饰器与匹配规则

## 用 @app.get 定义 GET 路由

在 FastAPI 中，使用 `@app.get("/路径")` 装饰器定义一个只响应 HTTP GET 请求的接口。GET 用于读取数据，参数通常放在 URL 查询串里。

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/users")
def list_users():
    return [{"id": 1, "name": "张三"}]
```

浏览器直接访问 `/users` 就能拿到 JSON 列表，不需要第三方序列化库，FastAPI 自动把返回的 dict/list 转成 JSON。

## 用 @app.post 定义 POST 路由

使用 `@app.post("/路径")` 定义 POST 接口，用于创建资源或提交数据。POST 请求的数据放在请求体中，而不是 URL 上。

```python
@app.post("/users")
def create_user(name: str):
    return {"created": name}
```

写一个 POST 接口的基本步骤：先 `@app.post("/users")` 声明路径，再在函数签名里声明需要接收的字段，FastAPI 会自动从请求体读取。

## 动态路由参数 {item_id}

路径里用花括号声明动态部分，例如 `@app.get("/items/{item_id}")`，花括号中的 `item_id` 会作为函数参数传入：

```python
@app.get("/items/{item_id}")
def get_item(item_id: int):
    return {"item_id": item_id}
```

访问 `/items/42` 时 `item_id` 的值是整数 42；如果访问 `/items/abc`，类型校验失败，FastAPI 直接返回 422 错误，不需要手写检查代码。

## 路由匹配顺序：先具体后动态

当多个路由可能匹配同一个 URL 时，FastAPI 按代码中声明的先后顺序匹配。应当把固定路径写在动态路径前面，否则 `/users/me` 会被 `/users/{user_id}` 抢先匹配，把字符串 `"me"` 当成 user_id。

```python
@app.get("/users/me")        # 先声明具体路径
def read_me():
    return {"user": "我自己"}

@app.get("/users/{user_id}") # 再声明动态路径
def read_user(user_id: int):
    return {"user_id": user_id}
```

记住一个原则：具体路由放前面，参数路由放后面。
