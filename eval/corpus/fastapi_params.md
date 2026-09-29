# FastAPI 参数：Path、Query 与校验

## Path 路径参数

路径参数是 URL 路径中的一部分，用 `Path()` 可以给它加校验规则和说明。下例要求 item_id 必须大于 0，否则返回 422：

```python
from fastapi import FastAPI, Path

app = FastAPI()

@app.get("/items/{item_id}")
def get_item(item_id: int = Path(..., gt=0, description="物品编号，必须为正整数")):
    return {"item_id": item_id}
```

`...`（Ellipsis）表示该参数必填。常见校验有 `gt`（大于）、`ge`（大于等于）、`lt`（小于）、`le`（小于等于）。

## Query 查询参数与默认值

URL 中 `?key=value` 形式的参数是查询参数，用 `Query()` 声明。可以给默认值让参数变成可选：`q: str = Query(default="fastapi", max_length=20)` 表示不传 q 时默认用 `"fastapi"`，且长度不能超过 20。

```python
from fastapi import Query

@app.get("/search")
def search(q: str = Query(default="", max_length=20), page: int = Query(default=1, ge=1)):
    return {"q": q, "page": page}
```

访问 `/search?q=python&page=2` 时 q 是 "python"、page 是 2；不传 page 时取默认值 1。

## Path 和 Query 的区别

Path 参数出现在 URL 路径里（`/items/42`），指向具体某个资源，通常必填；Query 参数跟在问号后面（`/items?page=2`），用于过滤、分页，通常可选且有默认值。两者都支持类型注解自动转换：声明成 int 就不会收到字符串。

## 参数缺失或非法时返回 422

如果必填参数没有传，或者传入的类型无法转换（例如把 "abc" 传给 int 参数），FastAPI 不会让请求进入函数体，而是自动返回 HTTP 422 Unprocessable Entity，并在响应体里指出是哪个字段、什么原因不合法。这套校验基于 Pydantic，开发者不用手写 if 判断。
