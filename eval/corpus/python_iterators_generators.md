# Python 迭代器与生成器

## 可迭代对象

实现了 `__iter__` 的对象是可迭代的；迭代器还实现了 `__next__`。`for` 循环先调用 `iter()` 得到迭代器，再不断调用 `next()` 直到 `StopIteration`。

## 生成器函数

函数体里出现 `yield` 就变成生成器函数，调用返回生成器对象而不立即执行。每次 `next()` 执行到下一个 yield 并暂停，局部变量保留。

```python
def read_in_chunks(lines):
    for line in lines:
        yield line.strip()
```

生成器惰性求值，内存占用与数据量无关，适合流式处理。

## 生成器表达式

`(x * 2 for x in items)` 是生成器表达式，相比列表推导式不一次性构建列表。管道式组合 `sum(x for x in ... if ...)` 很常见。

## send 与双向通信

生成器可以接收外部值：

```python
def accumulator():
    total = 0
    while True:
        value = yield total
        total += value
```

`send()` 把值传给 yield 表达式，`throw()` 在挂起点抛异常，`close()` 关闭生成器。协程的底层正是这种机制。

## yield from

`yield from sub_gen` 把迭代委托给子生成器，能简化嵌套迭代，并自动传递 send 与异常。适合把多个数据源串起来。

## itertools

`itertools.chain` 串联多个可迭代对象，`islice` 切片，`groupby` 分组（要求先排序），`count` 无限计数，`product` 笛卡尔积。善用这些工具能避免手写复杂循环。

## 一次性消费

生成器只能遍历一次，第二次为空。需要多次遍历时重新创建，或使用 `itertools.tee`（会缓存数据，内存增加）。调试时注意打印生成器只会显示对象地址。

## 与列表的区别

列表立即计算、可索引、可重复遍历；生成器惰性、不可索引、一次性。选择取决于数据量、是否需要随机访问、是否需要多次遍历。

## 常见坑

- 生成器被意外消费两次
- 在生成器里捕获异常后忘记 re-raise
- 依赖生成器的副作用顺序
- 用生成器处理需要随机访问的数据
- 忘记生成器也是迭代器，可被 next 直接驱动
