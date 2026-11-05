# SQLAlchemy ORM 基础

## Engine 与 Session

SQLAlchemy 2.0 的核心入口是 `create_engine`，它管理连接池与数据库方言。`sessionmaker` 生成会话工厂，会话负责身份映射、事务与查询。

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

engine = create_engine("sqlite:///app.db", echo=False)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
```

`expire_on_commit=False` 让提交后对象仍可访问，适合在提交后继续序列化响应；默认 True 会在提交后过期属性，再次访问触发查询，容易在会话关闭后报 `DetachedInstanceError`。

会话不是线程安全的，每个请求一个会话，请求结束关闭。异步框架里要用 `AsyncSession` 或把同步会话放进线程池执行，绝不能在事件循环里直接执行阻塞数据库调用。

## 声明式模型

2.0 推荐 `DeclarativeBase` 与 `Mapped` 注解：

```python
class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), index=True)
    email: Mapped[str] = mapped_column(unique=True)
```

`Mapped[str]` 默认非空，`Mapped[str | None]` 才允许 NULL。类型注解同时驱动 DDL 生成与编辑器类型提示。

## 查询方式

2.0 用 `select()` 构造查询，`session.execute()` 执行。`scalars()` 取出单个实体，`scalars().all()` 返回列表。

```python
stmt = select(User).where(User.name == "alice")
user = session.execute(stmt).scalar_one_or_none()
```

`scalar_one()` 要求恰好一条，零条或多条都会抛异常；`scalar_one_or_none()` 允许零条。用错会在数据异常时炸出难以理解的错误。

分页用 `offset()` 与 `limit()`，排序用 `order_by()`。大数据量下 offset 分页性能差，常见替代是游标分页，用上一页最后一条的排序键作为条件。

## 事务与提交

会话默认在第一次查询时开启事务，`commit()` 提交，`rollback()` 回滚。上下文管理器 `with SessionLocal() as session:` 会在退出时自动关闭，但不会自动提交。

一个请求内的多个写操作应放在同一事务中，保证原子性。不要在循环里逐条 commit，既慢又破坏原子性；批量插入用 `session.add_all()` 或 `bulk_insert_mappings()`。

## 更新与删除

直接改对象属性后 commit 即可，SQLAlchemy 会做脏检查生成 UPDATE。批量更新用 `update()` 语句，避免把大量对象加载进内存。

删除用 `session.delete(obj)`，或 `delete()` 语句批量删除。软删除（标记 deleted_at）在业务上更常见，查询时要记得过滤。

## N+1 问题

访问关联属性时如果会话还在，会触发额外查询。循环里访问关联对象就是经典的 N+1。解决方式是查询时用 `selectinload()` 或 `joinedload()` 预加载。

```python
stmt = select(User).options(selectinload(User.orders))
```

`joinedload` 用 JOIN 一次取回，适合一对一、多对一；`selectinload` 用第二条 IN 查询，适合一对多。预加载不是越多越好，过度 JOIN 会让单条 SQL 变重。

## 迁移

生产环境用 Alembic 管理表结构变更。模型改动后生成迁移脚本，人工检查再执行。不要在生产直接 `create_all()`，它不会处理字段变更与索引调整。
