# pytest 夹具与参数化

## fixture 基础

fixture 用 `@pytest.fixture` 声明，测试函数把名字作为参数即可获得返回值。fixture 负责准备与清理，yield 之前的代码是准备，之后的代码是清理。

```python
@pytest.fixture
def temp_store(tmp_path):
    store = VectorStore(path=tmp_path / "chroma")
    yield store
```

`tmp_path` 是 pytest 内置 fixture，提供每个用例独立的临时目录，测试结束自动清理，比手写 tempfile 更省心。

## fixture 作用域

`scope="function"` 是默认值，每个用例新建；`module`、`class`、`session` 分别共享到模块、类、整个会话。共享能加速，但会带来状态污染风险。数据库连接、外部客户端适合 session 级；会被修改的测试数据必须 function 级。

```python
@pytest.fixture(scope="session")
def app_client():
    ...
```

## 依赖注入与组合

fixture 可以依赖其他 fixture，形成依赖链。测试只声明最外层，内层自动解析。这让“构造对象”的代码集中在 fixture 里，测试函数只表达行为。

```python
@pytest.fixture
def fake_llm():
    return FakeLLM()

@pytest.fixture
def service(fake_llm):
    return ChatService(llm=fake_llm)
```

这也是依赖注入带来的可测性：service 在构造时接收协作者，测试时换成 Fake，无需 monkeypatch 私有属性。

## parametrize

`@pytest.mark.parametrize` 让同一逻辑跑多组数据，每组独立报告。

```python
@pytest.mark.parametrize("raw,expected", [("1", 1), (" 2 ", 2), ("x", None)])
def test_parse(raw, expected):
    assert parse(raw) == expected
```

参数名与测试函数参数对应。`ids=` 可以给每组数据起可读名字，失败时更容易定位。多组 parametrize 叠加会做笛卡尔积。

## 异常断言

`pytest.raises(ValueError, match="...")` 断言异常类型与消息。`match` 是正则，只匹配字符串表示的一部分。需要检查异常属性时用 `as exc_info` 拿到异常对象。

## 标记与跳过

`@pytest.mark.skipif(condition, reason=...)` 按条件跳过，适合缺少密钥、平台不支持的集成测试。自定义 marker 要在 `pytest.ini` 注册，否则会有警告。`@pytest.mark.xfail` 用于已知失败，但会掩盖回归，应谨慎。

## 断言与失败信息

Pytest 会对常见对象做详细 diff，列表、字典、字符串都会显示差异。断言消息可以加在 `assert x == y, "说明"`。一个测试只验证一个行为，失败时才能一眼定位原因。

## 测试隔离

每个用例应独立可重跑，不依赖执行顺序。常见污染源：模块级全局变量、真实数据库、环境变量、临时文件未清理。fixture 的 finalizer 与 `monkeypatch` 能保证恢复。

`monkeypatch` 自动还原属性、环境变量、工作目录，比手动改全局更安全。
