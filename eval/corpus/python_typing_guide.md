# Python 类型注解指南

## 基本注解

Python 3.10 起支持 `X | None` 写法，等价于 `Optional[X]`。函数返回值也要注解，返回 None 时写 `-> None`，不要省略。注解在运行时默认不校验，只用于静态检查与编辑器提示，Pydantic 等库会把注解当作运行时校验依据。

```python
def parse(raw: str) -> dict[str, int]:
    ...
```

## 容器类型

`list[int]`、`dict[str, int]`、`tuple[int, str]` 是内置泛型写法。`tuple[int, ...]` 表示变长同类型元组。只读场景可以用 `Sequence`、`Mapping`，让调用方知道不会修改。

## 泛型与 TypeVar

```python
T = TypeVar("T")

def first(items: list[T]) -> T:
    return items[0]
```

泛型函数能保持输入输出类型关联。Python 3.12 起可以用新的 `def first[T](items: list[T]) -> T` 语法，老版本仍用 TypeVar。约束用 `bound=BaseModel` 或 `constrained`。

## Protocol 结构化子类型

`Protocol` 定义“有哪些方法/属性”的接口，不要求继承。适合描述依赖的替身能力，测试时可以直接传 Fake 对象，无需继承真实类。

```python
class ChatClient(Protocol):
    def generate(self, prompt: str) -> str: ...
```

只要对象有匹配的方法就能通过类型检查，这就是鸭子类型的静态化写法。项目中常用它作为“构造缝”，让 service 依赖协议而不是具体实现。

## TypedDict 与 Literal

`TypedDict` 给字典声明键类型，适合描述 JSON 结构；`Literal["a", "b"]` 限定取值集合，适合状态字段、模式字段。Pydantic 对 `Literal` 会做严格校验，非法值直接 422。

## Callable 与重载

`Callable[[int], str]` 描述函数签名。函数行为随参数类型变化时可以用 `@overload` 声明多个签名，实现体只写一份。

## 类型收窄

`isinstance` 判断后类型检查器会自动收窄。`assert isinstance(x, Foo)` 既能收窄又能在运行时兜底。`cast` 告诉检查器“相信我”，但不会做运行时检查，滥用会掩盖错误。

## mypy 与 pyright

mypy 是常用静态检查器，`--strict` 开启最严格模式，会检查未注解的函数、Any 泄漏等。pyright 是微软实现，速度更快，VS Code 默认使用。CI 中可以只对核心模块开启严格模式，避免一次性被历史代码淹没。

## 常见坑

- 用 `dict` 而不是 `dict[str, int]`，丢失信息
- 注解写了但函数实际返回不匹配，运行时才炸
- `str | None` 与 `str = ""` 混用，语义不同
- 在 Pydantic 模型里用 `Any`，等于放弃校验
- 把类型注解当成运行时校验，直接相信外部数据
