# SQL 查询基础

SQL 用 SELECT 从表中读取数据，基本结构是 `SELECT 列 FROM 表 WHERE 条件`。
WHERE 子句过滤行，例如查询状态为 active 的用户：

```sql
SELECT id, name FROM users WHERE status = 'active';
```

多表关联用 JOIN。最常用的 INNER JOIN 只返回两表匹配成功的行，
下面的语句把订单和用户名拼在一起：

```sql
SELECT orders.id, users.name
FROM orders
INNER JOIN users ON orders.user_id = users.id;
```

分组统计用 GROUP BY，配合 COUNT、SUM、AVG 等聚合函数。
WHERE 过滤原始行，HAVING 过滤分组后的结果，二者顺序不能混用：

```sql
SELECT user_id, COUNT(*) AS n
FROM orders
GROUP BY user_id
HAVING COUNT(*) >= 3;
```

写入数据用 INSERT INTO，`INSERT INTO users (name) VALUES ('小王')`。
更新用 UPDATE、删除用 DELETE，两者都要带 WHERE，否则会改动整张表。

## 索引

索引（INDEX）相当于书的目录，能加速 WHERE 和 JOIN 上的查找，
但会占用存储并拖慢写入。频繁出现在过滤条件里的列适合建索引，
例如 `CREATE INDEX idx_users_status ON users(status);`。
