# Python 类型注解、dataclass 与 Pydantic

Python 的类型注解写在变量或参数后面，例如 `name: str`、`age: int = 0`，
返回值用箭头标注 `def f(x: int) -> str:`。注解默认不影响运行，
主要给 IDE 补全、静态检查和数据校验库使用。

标准库的 dataclasses 用装饰器批量生成 `__init__` 和 `__repr__`，
适合存放纯数据：

```python
from dataclasses import dataclass

@dataclass
class Item:
    name: str
    price: float
```

dataclass 只声明结构，运行时传错类型也不会报错。

## Pydantic 与数据校验

Pydantic 是建立在类型注解之上的数据校验库，模型类继承 BaseModel，
传入数据时它会按字段声明做类型校验并自动转换：能转成数字的字符串会被转成 int，
类型对不上或缺少必填字段时抛出 ValidationError，错误信息里带具体字段名。
因此凡是要在系统边界（外部 JSON、配置文件、表单）接收不可信数据的场合，
都适合用 Pydantic 模型先声明字段再校验，而不是手写一堆 isinstance 判断。
