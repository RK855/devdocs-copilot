# 同步、异步与 ASGI 基础

同步程序一行一行执行，遇到网络读写就要干等；异步程序基于事件循环，
用 async def 声明协程，遇到 await 的 I/O 操作时让出执行权，
单线程内同时维护大量连接。Python 里编写异步代码的标准库是 asyncio，
它负责调度协程，但本身不是 Web 服务器。

## WSGI 与 ASGI

WSGI 是 Python Web 的传统同步接口规范，Flask 和 Django 的普通视图都跑在
WSGI 服务器（如 gunicorn、uWSGI）上，一个请求占用一个线程。
ASGI 是新一代异步接口规范，原生支持 async/await、长连接和 WebSocket，
uvicorn 和 hypercorn 是常见的 ASGI 服务器实现。

选型上，只做普通 CRUD 的小服务用 WSGI 框架就够了；
需要高并发 I/O、流式响应或实时推送时，ASGI 的异步模型更合适。
注意 async 函数里不要直接调用会阻塞的库，否则会卡住整个事件循环，
应该用对应的异步库或把阻塞调用丢到线程池执行。
