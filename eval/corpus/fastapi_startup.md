# FastAPI 启动方式：uvicorn 与热重载

## 用 uvicorn main:app 启动服务

FastAPI 程序本身不监听端口，要交给 ASGI 服务器运行，最常用的是 uvicorn。假设 `main.py` 文件里有 `app = FastAPI()`，在项目根目录的虚拟环境中执行：

```bash
uvicorn main:app
```

`main` 是文件名（main.py），`app` 是文件里 FastAPI 实例的变量名，中间用冒号连接。启动后默认监听 `http://127.0.0.1:8000`，浏览器访问根路径看接口，访问 `/docs` 能看到自动生成的交互式 API 文档。

## --reload 热重载仅限开发环境

加上 `--reload` 参数后，uvicorn 会监视代码文件，一旦保存就自动重启服务：

```bash
uvicorn main:app --reload
```

热重载只适合本地开发，能省下手动重启的时间；生产环境不要开，因为文件监视和重启会带来额外开销与不稳定，生产部署应使用多 worker 模式。

## 指定主机与端口

默认只监听 127.0.0.1，本机以外访问不到。要用 `--host 0.0.0.0` 监听所有网卡，用 `--port 8080` 改端口：

```bash
uvicorn main:app --host 0.0.0.0 --port 8080
```

## 为什么不用 python main.py 直接运行

FastAPI/Starlette 应用是 ASGI 应用对象，不是普通脚本。直接 `python main.py` 不会启动网络监听，必须通过 uvicorn 这类 ASGI 服务器托管。也可以在代码底部用 `uvicorn.run("main:app", reload=True)` 以编程方式启动，效果与命令行相同。
