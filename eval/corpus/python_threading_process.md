# Python 线程与进程

## GIL 的影响

CPython 有全局解释器锁（GIL），同一时刻只有一个线程执行 Python 字节码。因此多线程对 CPU 密集任务没有加速效果，但 IO 密集任务会释放 GIL，多线程仍然有效。

多进程绕过 GIL，每个进程独立解释器，适合 CPU 密集计算。代价是进程间通信开销与内存占用。

## threading

`threading.Thread` 创建线程，`start()` 启动，`join()` 等待结束。线程共享内存，需要锁保护共享状态。

```python
lock = threading.Lock()
with lock:
    counter += 1
```

`threading.Event` 用于线程间通知，`Queue` 是线程安全的队列，适合生产者消费者模型。

## 线程池

`concurrent.futures.ThreadPoolExecutor` 管理线程池，避免频繁创建线程。`submit` 返回 Future，`map` 批量处理。池大小要匹配 IO 并发度，过大反而增加上下文切换。

asyncio 的 `to_thread` 底层也使用线程池，适合把阻塞调用移出事件循环。

## 进程池

`ProcessPoolExecutor` 适合 CPU 密集任务。参数与返回值必须可 pickle，不能传不可序列化的对象（如数据库连接、锁）。进程启动成本高，适合长任务而非大量小任务。

## 共享状态

多进程默认不共享内存。`multiprocessing.Value`、`Array` 提供共享内存，`Manager` 提供代理对象但性能较差。能用消息传递就不要共享状态。

## 竞态与死锁

竞态条件来自非原子的读改写。死锁通常来自多把锁的获取顺序不一致。固定顺序获取锁、设置超时、减少持锁时间是常见防御。

## 选择建议

- IO 密集：asyncio 或线程池
- CPU 密集：多进程
- 简单脚本：同步代码 + 少量线程
- Web 请求处理：优先 asyncio，阻塞库放线程池

## 常见坑

- 以为多线程能加速计算
- 持锁期间做网络请求
- 进程池传不可序列化对象
- 线程未 join 导致主进程提前退出
- 子线程异常无人捕获
