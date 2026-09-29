# Flask 路由入门

Flask 是 Python 的轻量级 Web 框架，用装饰器 `@app.route` 把 URL 路径绑定到视图函数。
下面的例子注册了一个读取数据的 GET 接口，浏览器直接访问就能看到返回文本：

```python
from flask import Flask

app = Flask(__name__)

@app.route("/users")
def list_users():
    return "user list"
```

路由默认只接受 GET 请求。要提供写入数据的 POST 接口，需要在装饰器的 `methods`
参数里显式声明 "POST"，再用 `request.get_json()` 从请求体读取 JSON 字段：

```python
from flask import request, jsonify

@app.route("/users", methods=["POST"])
def create_user():
    data = request.get_json()
    return jsonify({"created": data["name"]}), 201
```

注意 Flask 不会自动校验字段类型，客户端没传 name 时会直接抛 KeyError，需要自己用
`data.get("name")` 或 try/except 处理。路径参数用尖括号语法声明，例如
`@app.route("/users/<int:user_id>")`，Flask 会把它转成 int 传进视图函数。

## 启动方式

Flask 自带的开发服务器在脚本末尾调用 `app.run(debug=True)` 启动，监听 5000 端口。
debug 模式开启后代码改动会自动重载，但和 FastAPI 一样只能用于开发环境，
生产部署要用 gunicorn 这类 WSGI 服务器。Flask 基于 WSGI 同步模型，
而 FastAPI 基于 ASGI，原生支持 async def 视图。
