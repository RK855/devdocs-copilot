# 依赖注入（DI）与 FastAPI Depends

## 什么是依赖注入

依赖注入（Dependency Injection，DI）是一种设计思想：对象不自己创建它所依赖的东西，而是由外部把依赖"注"进来。好处是模块之间松耦合——代码只声明"我需要什么"，不关心"它从哪来、怎么构造"，因此在测试时可以轻松传入假对象（Stub/Fake）替换真实数据库连接或 HTTP 客户端。

## FastAPI 里用 Depends 声明依赖

在路径函数的参数里用 `Depends(依赖函数)` 声明需要的东西，FastAPI 会在调用函数前先执行依赖函数，把返回值传进来：

```python
from fastapi import Depends, FastAPI

app = FastAPI()

def get_db():
    db = {"k": "来自数据库的值"}
    return db

@app.get("/data")
def read_data(db=Depends(get_db)):
    # 不用自己调 get_db()，FastAPI 自动注入
    return db
```

依赖函数也可以带参数、可以嵌套依赖别的依赖，这套机制非常适合把鉴权、分页参数、数据库会话抽成公共组件，利于维护和权限控制。

## yield 依赖与生命周期

如果依赖需要打开/关闭资源（数据库连接、文件句柄），用生成器函数加 `yield`：`yield` 之前是初始化，`yield` 的值注入给路由，请求结束后执行收尾代码释放资源：

```python
def get_session():
    session = create_session()
    try:
        yield session
    finally:
        session.close()
```

## 依赖注入 vs 全局对象

直接使用全局对象（模块级的 `db = Database()`）写起来省事，但测试时无法替换、多请求共享状态容易互相污染；依赖注入把对象的创建推迟到请求时刻并通过参数传入，可替换、可嵌套、可按请求隔离生命周期，代价只是多一层函数声明。

## 为什么依赖注入利于测试

因为依赖是通过参数传入的，测试时把 `Depends(get_db)` 覆盖成返回内存假数据的函数，就能零数据库运行接口测试，断言更快更稳定。依赖注入也让横切关注点（鉴权、限流、日志）可以写成可复用的依赖，而不是在每个接口里重复代码。
