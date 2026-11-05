# 日期与时区处理

## 时间的两种表示

时间戳是绝对时刻，与时区无关；本地时间是“墙上时间”，依赖时区。存储应使用 UTC 时间戳或带时区的 datetime，展示时再转换到用户时区。

## datetime 基础

`datetime.now()` 返回本地朴素时间，不带时区；`datetime.now(timezone.utc)` 返回带时区时间。两者不能直接比较，会抛 TypeError。混合使用是时区 bug 的主要来源。

```python
from datetime import datetime, timezone

now = datetime.now(timezone.utc)
```

## aware 与 naive

带 `tzinfo` 的 datetime 是 aware，能正确比较与转换；naive 没有时区信息，含义模糊。项目内部统一使用 aware UTC，接口输入输出用 ISO 8601 字符串。

## 时区转换

`astimezone(ZoneInfo("Asia/Shanghai"))` 转换到目标时区。`zoneinfo` 是标准库，需要系统时区数据库；容器镜像缺少 tzdata 时会报错，需要显式安装。

## 格式化与解析

`strftime` 格式化，`strptime` 解析，`fromisoformat` 解析 ISO 字符串。解析失败要给出明确错误，不要静默回退到当前时间。

ISO 8601 示例：`2026-11-02T09:30:00+08:00`。带偏移量才能无歧义。

## 时间差

`timedelta` 表示时长，支持加减与比较。计算“几天前”时要注意夏令时，某些时区一天可能是 23 或 25 小时。跨时区业务尽量基于 UTC 计算时长。

## 数据库存储

数据库字段用带时区的类型（如 `TIMESTAMP WITH TIME ZONE`）或统一存 UTC。应用层读出来后转 aware。不要存本地时间字符串，排序与比较都会出错。

## 定时与超时

超时应该用单调时钟 `time.monotonic()` 或 `time.perf_counter()`，而不是系统时间，因为系统时间可能被校时跳变。日志时间戳用系统时间，便于与外部系统对齐。

## 常见坑

- naive 与 aware 混用
- 服务器时区与用户时区混淆
- 用本地时间存数据库
- 用系统时间计算耗时
- 容器缺 tzdata 导致时区转换失败
