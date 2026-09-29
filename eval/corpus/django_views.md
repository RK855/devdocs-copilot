# Django 视图与 URL 配置

Django 采用 MTV 结构：Model 描述数据表，Template 渲染页面，View 是处理请求的函数。
URL 与视图的绑定集中写在 `urls.py` 里，用 `path()` 声明，这与 Flask/FastAPI
用装饰器注册路由的风格不同：

```python
# urls.py
from django.urls import path
from . import views

urlpatterns = [
    path("articles/<int:article_id>/", views.article_detail),
]
```

视图函数接收一个 HttpRequest 对象，返回 HttpResponse：

```python
# views.py
from django.http import HttpResponse

def article_detail(request, article_id):
    if request.method == "GET":
        return HttpResponse(f"article {article_id}")
```

返回 JSON 可以用 `django.http.JsonResponse`，它会自动设置 Content-Type。
读取 POST 表单用 `request.POST.get("title")`，读取 JSON 请求体则要用
`json.loads(request.body)`——Django 默认面向表单，不像 FastAPI 那样用 Pydantic
自动解析和校验 JSON 字段，类型校验需要自己写或借助序列化器。

## ORM 与数据库

Django 内置 ORM，模型类继承 `models.Model`，执行 `python manage.py makemigrations`
和 `migrate` 后自动建表。查询用 `Article.objects.filter(id=article_id).first()`，
外键关联用双下划线，例如 `Comment.objects.filter(article__title="入门")`。
启动项目统一用 `python manage.py runserver`，不要在代码里直接运行脚本。
