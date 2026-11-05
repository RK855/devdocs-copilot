# Pydantic 模型设计

## BaseModel 基础

Pydantic v2 的模型继承 `BaseModel`，字段用类型注解声明。实例化时自动校验与转换，不合法会抛 `ValidationError`，FastAPI 会把它转成 422 响应。

```python
from pydantic import BaseModel, Field

class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    age: int = Field(ge=0, le=150)
    email: str
```

`Field` 用于补充约束与元信息：`min_length`、`max_length`、`ge`、`le`、`pattern`、`description`、`default`。约束写进模型比写在业务代码里更好，因为校验发生在入口，错误信息也统一。

## 默认值与可选字段

`name: str = "anonymous"` 表示有默认值；`name: str | None = None` 表示可缺省且允许 null。区别很重要：前者在缺省时是空字符串之外的默认值，后者缺省时是 None。业务上如果字段“可以不传但不能是 null”，要分别处理。

Pydantic v2 中可变默认值（list、dict）会被自动深拷贝，不需要 `default_factory` 也不会出现共享引用问题，但用 `default_factory=list` 语义更明确。

## 输入模型与输出模型分离

不要直接把数据库实体或内部对象当响应模型。输入模型负责校验客户端数据，输出模型负责裁剪敏感字段并稳定契约。例如 `UserIn` 不含 id，`UserOut` 不含 password_hash。

```python
class UserOut(BaseModel):
    id: int
    name: str
    model_config = ConfigDict(from_attributes=True)
```

`from_attributes=True` 允许从对象属性构造，配合 ORM 对象使用。响应模型还能过滤多余字段，避免内部字段意外泄露。

## 嵌套与列表模型

嵌套模型可以表达复杂请求体，例如订单包含多个商品项。Pydantic 会递归校验，错误 `loc` 会带上嵌套路径如 `body.items.0.price`。

```python
class Item(BaseModel):
    sku: str
    qty: int = Field(gt=0)

class Order(BaseModel):
    items: list[Item] = Field(min_length=1)
```

列表长度约束用 `min_length` / `max_length`。大批量数据要注意上限，避免超长请求拖垮服务，通常还要在网关层限制请求体大小。

## 别名与序列化

外部 API 常用 camelCase，内部用 snake_case。`Field(alias="userId")` 或 `model_config = ConfigDict(populate_by_name=True)` 可以兼顾。序列化时用 `by_alias=True` 输出别名。

`model_dump()` 返回字典，`model_dump_json()` 返回 JSON 字符串。`exclude_unset=True` 只输出显式设置的字段，适合 PATCH 语义。

## 配置与严格模式

`ConfigDict(extra="forbid")` 拒绝未知字段，适合对外接口，能尽早发现拼写错误；`extra="ignore"` 忽略未知字段，适合兼容上游变更。`strict=True` 禁止类型隐式转换，例如拒绝把字符串 "1" 转成整数 1。

## 常见坑

- 用 `dict` 而不是模型接收请求体，会失去校验与文档
- 在响应模型里暴露内部 id 或密钥字段
- 用 `str` 接收数字再手动 int()，等于放弃校验
- 校验失败直接返回 500，而不是让 FastAPI 的 422 生效
- 模型里写数据库查询，导致模型与存储耦合
