# Python dataclass 与数据容器

## dataclass 基础

`@dataclass` 自动生成 `__init__`、`__repr__`、`__eq__`，适合承载数据的简单类。

```python
from dataclasses import dataclass, field

@dataclass
class Chunk:
    doc_id: str
    index: int
    text: str
    score: float = 0.0
    tags: list[str] = field(default_factory=list)
```

可变默认值必须用 `field(default_factory=list)`，直接写 `[]` 会抛错，因为所有实例会共享同一个列表。

## frozen 与不可变

`@dataclass(frozen=True)` 让实例不可修改，可以安全地作为字典键或集合元素。需要“修改”时用 `dataclasses.replace()` 生成新实例。不可变对象在并发场景更安全，也便于推理。

## 排序与比较

`order=True` 自动生成比较方法，按字段声明顺序比较。只想按部分字段排序时指定 `field(compare=False)`。排序键更复杂时写 `key` 函数更清晰。

## slots

`@dataclass(slots=True)` 用 `__slots__` 限制属性，减少内存占用并防止拼写错误创建新属性。大量小对象时收益明显。

## 与 Pydantic 的区别

dataclass 是纯数据容器，不做运行时校验；Pydantic 模型负责入口校验与序列化。常见组合：内部传递用 dataclass，接口边界用 Pydantic。两者都支持类型注解，但职责不同。

## asdict 与序列化

`dataclasses.asdict()` 递归转字典，适合简单结构。包含 datetime 或嵌套对象时需要自定义处理。JSON 序列化前要确认所有字段可序列化。

## NamedTuple

`NamedTuple` 是不可变元组，支持索引访问与解包，适合轻量返回值。相比 dataclass 更轻，但字段不能有默认值逻辑，也不支持方法之外的复杂行为。

## 常见坑

- 可变默认值共享
- 用 dataclass 承载需要校验的外部输入
- frozen 对象内部仍持有可变列表
- 大量对象未用 slots 导致内存膨胀
- 依赖自动生成的 repr 打印超大字段
