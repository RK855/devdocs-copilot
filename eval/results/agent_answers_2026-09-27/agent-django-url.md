# agent-django-url（跨框架）

- 期望：agent；实际：agent；degraded：False
- 耗时：24.02s；调用 4 次 / 2 轮；失败步 0
- 缺失关键词：无

## 答案



在 Django 中，URL 与视图的绑定集中写在 `urls.py` 文件里，使用 `path()` 声明。

## 基本用法

```python
# urls.py
from django.urls import path
from . import views

urlpatterns = [
    path("articles/<int:article_id>/", views.article_detail),
]
```

```python
# views.py
from django.http import HttpResponse

def article_detail(request, article_id):
    return HttpResponse(f"article {article_id}")
```

## 关键要点

| 特性 | 说明 |
|------|------|
| `path()` 位置参数 1 | URL 路径字符串 |
| `path()` 位置参数 2 | 视图函数 |
| `<转换器:参数名>` | 路径参数，如 `<int:article_id>` |
| 参数传递 | Django 自动把转换后的值传入视图函数 |

## 常用内置转换器

- `str`：除 `/` 外的非空字符串
- `int`：正整数
- `slug`：由字母、数字、横线、下划线组成的字符串
- `uuid`：UUID 格式
- `path`：匹配除 `/` 外的任意字符（包含 `/`）

## 路由顺序规则

当多个路由可能匹配同一个 URL 时，**按声明顺序匹配**。固定路径应写在动态路径前面：

```python
urlpatterns = [
    path("articles/special/", views.special_article),  # 先写具体路径
    path("articles/<int:article_id>/", views.article_detail),  # 再写动态路径
]
```

否则 `/articles/special/` 会被第二条路由抢先匹配。

## 多 app 路由组织

```python
# project/urls.py
from django.urls import path, include

urlpatterns = [
    path("articles/", include("articles.urls")),
    path("users/", include("users.urls")),
]
```

```python
# articles/urls.py
from django.urls import path
from . import views

app_name = "articles"  # 命名空间

urlpatterns = [
    path("", views.article_list, name="list"),
    path("<int:article_id>/", views.article_detail, name="detail"),
]
```

然后用 `reverse("articles:detail", args=[article_id])` 反向生成 URL。

## 视图函数签名

视图函数至少接收一个参数 `request`（`HttpRequest` 对象），后续参数对应 `path()` 中捕获的路径参数：

```python
def article_detail(request, article_id: int):
    # 处理请求
    return HttpResponse(f"article {article_id}")
```

## steps

```json
[
  {
    "step": 1,
    "tool": "search_docs",
    "arguments": {
      "query": "Django URL 绑定 视图函数 urlpath path",
      "top_k": 5
    },
    "result_count": 5,
    "cached": false,
    "status": "ok",
    "error": null
  },
  {
    "step": 2,
    "tool": "search_docs",
    "arguments": {
      "query": "Django urls.py include app_name namespace",
      "top_k": 5
    },
    "result_count": 5,
    "cached": false,
    "status": "ok",
    "error": null
  },
  {
    "step": 2,
    "tool": "search_docs",
    "arguments": {
      "query": "Django path converter 路径参数",
      "top_k": 5
    },
    "result_count": 5,
    "cached": false,
    "status": "ok",
    "error": null
  },
  {
    "step": 2,
    "tool": "search_docs",
    "arguments": {
      "query": "Django URL反向解析 urlname",
      "top_k": 5
    },
    "result_count": 5,
    "cached": false,
    "status": "ok",
    "error": null
  }
]
```
