# agent-startup（概念）

- 期望：agent；实际：agent；degraded：False
- 耗时：19.8s；调用 2 次 / 1 轮；失败步 0
- 缺失关键词：无

## 答案



FastAPI 应用需要借助 **ASGI 服务器** 启动，最常用的是 **uvicorn**。

## 基本启动命令

假设你的项目入口文件是 `main.py`，里面定义了 `app = FastAPI()`：

```bash
uvicorn main:app
```

- `main`：文件名（不含 `.py`）
- `app`：FastAPI 实例的变量名
- 默认监听 `http://127.0.0.1:8000`
- 访问 `/docs` 可看到自动生成的交互式 API 文档

## 开发环境：热重载

```bash
uvicorn main:app --reload
```

代码保存后自动重启，**仅限本地开发**，生产环境禁用。

## 指定主机与端口

```bash
uvicorn main:app --host 0.0.0.0 --port 8080
```

- `--host 0.0.0.0`：监听所有网卡（否则默认仅本机可访问）
- `--port 8080`：自定义端口

## 为什么不能直接 `python main.py`

FastAPI 应用是 ASGI 对象，不是普通脚本。直接运行不会启动网络监听，必须通过 uvicorn 托管。也可以在代码中编程启动：

```python
import uvicorn

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
```

## 生产部署

生产环境建议使用多 worker 模式，例如配合 **gunicorn** 使用：

```bash
gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app
```

或直接使用 uvicorn 的生产参数：

```bash
uvicorn main:app --host 0.0.0.0 --port 80 --workers 4
```

## steps

```json
[
  {
    "step": 1,
    "tool": "search_docs",
    "arguments": {
      "query": "FastAPI 应用启动 uvicorn",
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
      "query": "FastAPI application startup",
      "top_k": 5
    },
    "result_count": 5,
    "cached": false,
    "status": "ok",
    "error": null
  }
]
```
