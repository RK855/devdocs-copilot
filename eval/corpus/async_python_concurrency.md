# Python 异步并发

## 事件循环

asyncio 的核心是事件循环，它在单线程里调度协程。协程遇到 `await` 时让出控制权，循环去执行其他任务。因此异步适合 IO 密集型场景，不适合 CPU 密集型场景。

一个线程只有一个运行中的事件循环。`asyncio.run()` 创建循环、运行协程、关闭循环，适合脚本入口。在已有循环中调用 `asyncio.run()` 会报错，Jupyter 与部分框架里常见这个坑。

## 协程与任务

协程对象只有被 await 或被包装成 Task 才会执行。`asyncio.create_task()` 立即调度，适合后台并行；`asyncio.gather()` 并发等待多个协程并收集结果。

```python
results = await asyncio.gather(fetch(a), fetch(b), fetch(c))
```

`gather` 默认遇到异常会向上传播，但其他任务不会自动取消。需要“一个失败就全部取消”时，用 `TaskGroup`：

```python
async with asyncio.TaskGroup() as tg:
    tg.create_task(fetch(a))
    tg.create_task(fetch(b))
```

Python 3.11 起 TaskGroup 是结构化并发的推荐写法，异常会以 ExceptionGroup 形式抛出。

## 超时控制

`asyncio.wait_for(coro, timeout=5)` 超时会抛 `TimeoutError` 并取消协程。Python 3.11 起也可以用 `asyncio.timeout()` 上下文管理器。超时后要确保底层连接被释放，否则资源会泄漏。

## 同步阻塞调用

在协程里直接调用 `requests.get()`、`time.sleep()`、同步数据库驱动会阻塞整个事件循环，所有并发请求一起变慢。正确做法是用 `asyncio.to_thread()` 把阻塞调用丢到线程池。

```python
result = await asyncio.to_thread(blocking_io, arg)
```

`to_thread` 会使用默认线程池，默认大小受 `min(32, cpu+4)` 限制。大量并发阻塞调用要评估线程池容量，必要时自定义 `ThreadPoolExecutor`。

注意 `to_thread` 只解决“不阻塞事件循环”，不解决资源线程安全问题。某些同步客户端必须在创建它的线程里关闭，跨线程关闭会导致连接泄漏，这类对象需要在同一个线程内完成创建、使用、关闭的完整生命周期。

## 锁与竞争

异步代码里共享可变状态仍需要保护。`asyncio.Lock` 用于协程间互斥，`asyncio.Semaphore` 用于限制并发数，例如限制对上游 API 的同时请求数。

```python
sem = asyncio.Semaphore(5)
async with sem:
    await call_upstream()
```

不要在持锁期间做长时间等待，容易造成全局串行。

## 取消与清理

任务被取消时会在 await 点抛 `CancelledError`。`finally` 里做清理，但清理逻辑本身不应再 await 太久。捕获 `CancelledError` 后如果不重新抛出，会破坏取消语义，通常只在需要记录日志时捕获再 raise。

## 常见坑

- 用 `time.sleep` 而不是 `asyncio.sleep`
- 在协程里同步读大文件
- 忘记 await，协程从未执行
- `gather` 里异常被吞掉，因为 `return_exceptions=True`
- 长任务没有超时，上游卡死时请求永远挂着
