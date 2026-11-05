# Pydantic 校验器

## field_validator

Pydantic v2 用 `@field_validator` 自定义单字段校验。默认在类型转换之后执行，可以拿到已经是目标类型的值。

```python
from pydantic import BaseModel, field_validator

class Signup(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v:
            raise ValueError("邮箱格式不正确")
        return v
```

校验器抛 `ValueError` 会被包装成 `ValidationError`，错误位置指向对应字段。不要在校验器里抛 `HTTPException`，模型层不应该知道 HTTP。

`mode="before"` 让校验器在类型转换前执行，适合清洗原始输入，例如把 `"1"` 转成 `1`、把空字符串转成 None。`mode="after"` 是默认行为。

## model_validator

跨字段校验用 `@model_validator(mode="after")`，此时所有字段都已校验完成，可以访问 `self`。

```python
@model_validator(mode="after")
def check_range(self):
    if self.start >= self.end:
        raise ValueError("start 必须小于 end")
    return self
```

`mode="before"` 拿到的是原始字典，适合做字段重命名或结构适配。返回 `self` 是 v2 的硬性要求，忘记返回会导致模型变成 None。

## 序列化器

`@field_serializer` 控制输出格式，例如把 datetime 转成 ISO 字符串、把枚举转成中文文案。序列化器只影响输出，不参与校验。

`@model_serializer` 控制整个模型的输出结构，适合需要动态增减字段的场景，但会牺牲部分类型推断能力。

## 校验错误信息

自定义校验失败时，错误消息应直接面向使用者，说明“哪里错了、期望什么”。避免抛出“invalid value”这类无信息量的文案。Pydantic 会把消息放进 `msg` 字段，前端可以直接展示。

## 校验与业务规则的分界

格式类规则放模型：长度、正则、范围、枚举、必填。业务类规则放 service：唯一性、状态流转、权限、余额充足。把业务规则塞进校验器会导致模型依赖数据库，难以测试，也让错误处理混乱。

例如“用户名不能重复”需要查询数据库，不应该写在 validator 里；而“用户名只能包含字母数字下划线”属于格式，适合写在校验器。

## 复用与继承

多个模型共享字段时，可以定义基类再继承。Pydantic 支持模型继承，字段会合并。注意不要为了复用而构造过深的继承树，组合通常比继承更清晰。

`Annotated` 可以把常用约束抽成类型别名：

```python
Username = Annotated[str, Field(min_length=3, max_length=20, pattern=r"^[a-zA-Z0-9_]+$")]
```

这样多个模型复用同一套约束，修改时只改一处。

## 性能注意

校验器在每次请求都会执行，避免在 validator 里做网络请求或重计算。Pydantic v2 的核心用 Rust 实现，常规校验很快，但自定义 Python 校验器会成为热点。大列表校验可以用 `TypeAdapter` 复用校验逻辑，避免重复构造模型类。
