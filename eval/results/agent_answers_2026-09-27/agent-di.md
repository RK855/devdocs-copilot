# agent-di（概念）

- 期望：agent；实际：agent；degraded：False
- 耗时：10.22s；调用 2 次 / 1 轮；失败步 0
- 缺失关键词：无

## 答案



## 什么是依赖注入

依赖注入（DI）是一种设计思想：**对象不自己创建依赖，而是由外部把依赖"注"进来**。好处是松耦合——代码只声明"我需要什么"，不关心"它从哪来、怎么构造"，测试时也能轻松传入假对象（Stub/Fake）替换真实数据库连接或 HTTP 客户端。

## FastAPI 里怎么声明依赖

在路径函数的参数里用 `Depends(依赖函数)` 声明，FastAPI 会自动调用依赖函数，并把返回值传进路由：

```python
from fastapi import Depends, FastAPI

app = FastAPI()

def get_db():
    db = {"k": "来自数据库的值"}
    return db

@app.get("/data")
def read_data(db=Depends(get_db)):
    return db
```

### 常见用法

- **依赖嵌套**：依赖函数也可以 `Depends` 别的依赖
- **带参数的依赖**：依赖函数本身可以有参数，FastAPI 会递归注入
- **生命周期管理**：用 `yield` 替代 `return` 可以处理资源清理

```python
def get_session():
    session = create_session()
    try:
        yield session      # 请求开始时初始化
    finally:
        session.close()    # 请求结束时释放资源
```

### 为什么比全局对象更好

直接使用全局对象（如模块级的 `db = Database()`）写起来省事，但：
- 测试时无法替换
- 多请求共享状态容易互相污染
- 无法按请求隔离生命周期

依赖注入把对象创建推迟到请求时刻，可替换、可嵌套、可隔离，代价只是多一层函数声明。

## steps

```json
[
  {
    "step": 1,
    "tool": "search_docs",
    "arguments": {
      "query": "FastAPI 依赖注入 声明依赖 dependency injection",
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
      "query": "FastAPI Depends 依赖函数 yield",
      "top_k": 5
    },
    "result_count": 5,
    "cached": false,
    "status": "ok",
    "error": null
  }
]
```
