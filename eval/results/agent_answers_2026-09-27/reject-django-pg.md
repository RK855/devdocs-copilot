# reject-django-pg（库外）

- 期望：reject；实际：agent；degraded：False
- 耗时：29.74s；调用 6 次 / 3 轮；失败步 0
- 缺失关键词：无

## 答案



根据知识库检索结果，暂未找到 Django 配置 PostgreSQL 的详细文档内容。以下是标准配置方法：

## Django 配置 PostgreSQL 数据库连接

### 1. 安装 psycopg2 适配器

```bash
# 方式一：完整功能版（需要编译 C 库）
pip install psycopg2-binary

# 方式二：轻量版（生产环境推荐，需系统安装 libpq-dev）
pip install psycopg2
```

### 2. 修改 `settings.py` 中的 `DATABASES`

```python
# settings.py
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',  # 指定 PostgreSQL 引擎
        'NAME': 'my_database',                       # 数据库名
        'USER': 'myuser',                            # 数据库用户名
        'PASSWORD': 'mypassword',                    # 数据库密码
        'HOST': 'localhost',                         # 数据库主机地址
        'PORT': '5432',                              # 端口（PostgreSQL 默认 5432）
    }
}
```

### 3. 使用数据库 URL（可选）

也可以直接使用连接字符串：

```python
import dj_database_url

DATABASES = {
    'default': dj_database_url.config(
        default='postgres://myuser:mypassword@localhost:5432/my_database'
    )
}
```

### 4. 迁移数据库

```bash
python manage.py makemigrations
python manage.py migrate
```

---

**说明**：以上为 Django 官方标准配置方式。如需更详细的参数说明或特定版本差异，建议查阅 Django 官方文档中 [Database configuration](https://docs.djangoproject.com/en/stable/ref/databases/) 部分。

## steps

```json
[
  {
    "step": 1,
    "tool": "search_docs",
    "arguments": {
      "query": "Django PostgreSQL 数据库配置 DATABASES settings",
      "top_k": 5
    },
    "result_count": 5,
    "cached": false,
    "status": "ok",
    "error": null
  },
  {
    "step": 1,
    "tool": "search_docs",
    "arguments": {
      "query": "Django psycopg2 postgres configuration database",
      "top_k": 5
    },
    "result_count": 0,
    "cached": false,
    "status": "empty",
    "error": null
  },
  {
    "step": 2,
    "tool": "search_docs",
    "arguments": {
      "query": "DATABASES settings.py PostgreSQL postgres ENGINE",
      "top_k": 5
    },
    "result_count": 0,
    "cached": false,
    "status": "empty",
    "error": null
  },
  {
    "step": 2,
    "tool": "search_docs",
    "arguments": {
      "query": "Django database configuration postgres adapter psycopg",
      "top_k": 5
    },
    "result_count": 0,
    "cached": false,
    "status": "empty",
    "error": null
  },
  {
    "step": 3,
    "tool": "search_docs",
    "arguments": {
      "query": "Django 配置 数据库 PostgreSQL 连接 settings",
      "top_k": 5
    },
    "result_count": 5,
    "cached": false,
    "status": "ok",
    "error": null
  },
  {
    "step": 3,
    "tool": "search_docs",
    "arguments": {
      "query": "django postgres database engine settings DATABASE",
      "top_k": 5
    },
    "result_count": 5,
    "cached": false,
    "status": "ok",
    "error": null
  }
]
```
