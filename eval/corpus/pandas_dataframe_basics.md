# Pandas 数据处理基础

## DataFrame 与 Series

DataFrame 是带行列标签的二维表格，Series 是带索引的一维序列。列可以有不同的 dtype，但每列内部类型一致。

```python
import pandas as pd

df = pd.DataFrame({"name": ["a", "b"], "score": [90, 85]})
```

## 读取与写出

`read_csv`、`read_excel`、`read_json` 读取数据，`to_csv`、`to_excel` 写出。读取时注意编码、分隔符、缺失值标记。大文件用 `chunksize` 分块处理。

## 选择数据

`df["col"]` 取列，`df.loc[行标签, 列名]` 按标签选择，`df.iloc[行号, 列号]` 按位置选择。布尔过滤 `df[df["score"] > 80]`。链式赋值可能触发 SettingWithCopyWarning，应使用 `.loc` 一次性赋值。

## 缺失值

`isna()` 判断缺失，`dropna()` 删除，`fillna()` 填充。填充策略要符合业务，数值用中位数、分类用众数或单独标记。不要无脑填 0，会扭曲统计。

## 分组聚合

`groupby` 按列分组后聚合：

```python
df.groupby("dept")["score"].agg(["mean", "count", "max"])
```

`agg` 支持多个函数，`transform` 返回与原表同形状的结果，适合做组内标准化。

## 合并

`merge` 类似 SQL JOIN，`how` 取 inner/left/right/outer。`on` 指定连接键，键类型不一致会导致匹配失败。合并后检查行数变化，防止一对多导致数据膨胀。

`concat` 沿轴拼接，适合纵向追加。

## 排序与去重

`sort_values(by=..., ascending=False)` 排序，`drop_duplicates(subset=[...])` 去重。去重前想清楚保留哪一条，`keep="first"` 或 `keep="last"`。

## 时间序列

`to_datetime` 转时间类型，`resample` 重采样，`rolling` 滑动窗口。时间列设为索引后切片更方便。

## 性能

向量化操作优于 `apply`。`apply` 逐行调用 Python 函数，慢。必须有复杂逻辑时再考虑。分类列用 `category` dtype 省内存。大表避免反复复制。

## 常见坑

- 链式赋值产生副本修改无效
- 忽略 dtype 导致数值当字符串
- merge 后行数暴涨
- 缺失值填充策略不合理
- 用 iterrows 遍历大表
