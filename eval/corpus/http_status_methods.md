# HTTP 状态码与请求方法

## 请求方法的语义

GET 获取资源，应当是安全且幂等的，不改变服务端状态。POST 创建资源或执行动作，不保证幂等。PUT 全量替换资源，幂等。PATCH 局部更新，不保证幂等但通常设计成幂等。DELETE 删除资源，幂等。

幂等指重复执行结果相同。网络超时后客户端重试，幂等方法可以安全重试；非幂等方法需要幂等键防止重复创建。

## 2xx 成功

- 200 OK：通用成功，GET 与 PUT 常用
- 201 Created：创建成功，响应头应带 Location
- 202 Accepted：已接受但异步处理，返回任务 id
- 204 No Content：成功但无响应体，适合 DELETE

## 3xx 重定向

301 永久重定向，搜索引擎会更新索引；302/307 临时重定向，307 保留原方法。308 永久且保留方法。API 中应谨慎使用重定向，客户端未必跟随。

## 4xx 客户端错误

- 400 Bad Request：请求格式错误
- 401 Unauthorized：未认证，缺少或无效凭证
- 403 Forbidden：已认证但无权访问
- 404 Not Found：资源不存在
- 405 Method Not Allowed：方法不支持
- 409 Conflict：状态冲突，例如重复创建
- 422 Unprocessable Entity：格式正确但语义校验失败
- 429 Too Many Requests：触发限流，应带 Retry-After

401 与 403 的区别常被搞混：401 是“你是谁”，403 是“你不能”。认证失败用 401，授权失败用 403。

## 5xx 服务端错误

- 500 Internal Server Error：未预期异常
- 502 Bad Gateway：网关收到上游无效响应
- 503 Service Unavailable：服务过载或维护，可带 Retry-After
- 504 Gateway Timeout：上游超时

不要把可预期的业务失败映射成 5xx，否则监控会把它当成服务故障。

## 请求头与响应头

`Content-Type` 声明媒体类型，JSON 为 `application/json`，SSE 为 `text/event-stream`。`Accept` 表示客户端期望的响应类型。`Authorization` 携带凭证。`X-Request-Id` 常用于链路追踪。

缓存相关：`Cache-Control`、`ETag`、`Last-Modified`。写操作响应通常不缓存。

## 幂等键

创建类接口可以要求客户端传 `Idempotency-Key`，服务端记录键与结果，重复请求直接返回首次结果。这是支付、订单类接口的标准做法。

## 版本与兼容

URL 加 `/v1`、请求头加版本、或媒体类型带版本都是常见方案。无论哪种，新增字段是兼容的，删除或改语义是不兼容的，需要新版本。

## 常见坑

- 所有错误都返回 200
- 401 与 403 混用
- DELETE 返回 200 且带空 JSON，而不是 204
- 创建成功返回 200 而不是 201
- 限流不返回 429 与 Retry-After
