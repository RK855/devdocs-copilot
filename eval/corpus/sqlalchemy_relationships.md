# SQLAlchemy 关系映射

## 一对多

一对多是最常见的关系：一个用户多个订单。在“多”一侧放外键，在“一”一侧用 `relationship` 声明集合。

```python
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    orders: Mapped[list["Order"]] = relationship(back_populates="user")

class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    user: Mapped["User"] = relationship(back_populates="orders")
```

`back_populates` 双向声明，两边都要写，保证内存中对象关系同步。只写一边会导致刷新后关系不一致。

## 多对多

多对多需要中间表。用 `Table` 定义关联表，再在两侧声明 `secondary`。

```python
association = Table(
    "post_tags", Base.metadata,
    Column("post_id", ForeignKey("posts.id"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id"), primary_key=True),
)

class Post(Base):
    tags: Mapped[list["Tag"]] = relationship(secondary=association, back_populates="posts")
```

中间表如果还要存额外字段（例如创建时间、排序），就应该升级成独立的关联对象模型，用两个一对多替代多对多。

## 级联删除

`cascade="all, delete-orphan"` 表示删除父对象时删除子对象，且从集合中移除的子对象会被删除。数据库层面的 `ondelete="CASCADE"` 是另一层保障。

两层容易混淆：ORM 级联由会话在内存中处理，数据库级联由数据库执行。批量删除走 SQL 时不经过 ORM，必须依赖数据库级联或手动删除子表。两者都配是最稳的，但要确保语义一致，避免双重删除或漏删。

## 懒加载与预加载

默认 `lazy="select"` 是懒加载，访问属性时才查询。在会话关闭后访问会报错，在循环里访问会产生 N+1。

`lazy="raise"` 强制必须显式预加载，适合严格团队，能把 N+1 提前暴露成错误。`lazy="dynamic"` 返回查询对象，适合超大集合分页，但 2.0 中更推荐显式查询。

## 关系查询

按关联条件过滤用 `join()` 或 `has()`：

```python
stmt = select(User).where(User.orders.any(Order.amount > 100))
stmt = select(User).join(User.orders).where(Order.status == "paid")
```

`any()` 生成 EXISTS 子查询，适合过滤；`join()` 适合需要同时取关联字段或聚合。多对多 join 会重复主表行，需要 `distinct()`。

## 自引用关系

树形结构用自引用外键，并指定 `remote_side`：

```python
parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
children: Mapped[list["Category"]] = relationship(back_populates="parent")
parent: Mapped["Category | None"] = relationship(remote_side="Category.id", back_populates="children")
```

`remote_side` 告诉 ORM 哪一端是“一”端，否则无法推断方向。

## 常见坑

- 忘记 `back_populates` 导致双向不同步
- 在异步会话里使用懒加载，触发隐式 IO 报错
- 在循环里逐条查询关联对象造成 N+1
- 级联配置与数据库约束不一致，删除行为不可预测
- 把关系当成普通列表随意 append，却忘记 commit
