# JWT 认证流程

## JWT 的结构

JWT 由三段 Base64URL 字符串组成，用点分隔：`header.payload.signature`。header 声明算法与类型，payload 携带声明（claims），signature 用密钥对前两段签名。payload 只是编码，不是加密，任何人都能解开查看，绝不能放密码等敏感信息。

## 常见声明

`sub` 表示主体（用户 id），`exp` 过期时间，`iat` 签发时间，`nbf` 生效时间，`aud` 受众，`iss` 签发者。业务自定义声明要避免与标准名冲突。

## 签发流程

1. 用户提交账号密码
2. 服务端校验通过
3. 生成 access token（短寿命，如 15 分钟）与 refresh token（长寿命，如 7 天）
4. access token 返回给客户端，refresh token 存 HttpOnly Cookie 或安全存储
5. 客户端请求时带 `Authorization: Bearer <access token>`

## 校验流程

服务端验证签名、算法、过期时间、受众。必须显式指定允许的算法，绝不能从 token 的 header 里读取算法，否则会有算法混淆攻击（把 RS256 改成 HS256 并用公钥当密钥）。

校验失败返回 401，并在 `WWW-Authenticate` 头说明原因。

## 刷新与轮换

access token 过期后用 refresh token 换新的。refresh token 应一次性使用并轮换，服务端记录已用过的 token，检测重复使用视为泄露并吊销整条链。

## 存储位置

localStorage 方便但易受 XSS 窃取；HttpOnly Cookie 防 XSS 但需要防 CSRF。常见折中：access token 放内存，refresh token 放 HttpOnly Cookie，配合 SameSite 与 CSRF token。

## 无状态与吊销

JWT 天然无状态，服务端不存会话，扩展性好。代价是吊销困难：签发了就有效到过期。解决方案：

- access token 短寿命，减少窗口
- 维护黑名单（存已吊销的 jti），牺牲部分无状态性
- 用版本号声明，用户改密码后版本递增，旧 token 全部失效

## 与 Session 的对比

Session 存服务端，可随时吊销，但需要共享存储；JWT 无状态易扩展，但吊销麻烦、体积更大。选择取决于是否需要强吊销与横向扩展需求。

## 常见坑

- 把敏感信息放 payload
- 不校验 exp
- 允许任意算法
- 密钥硬编码在代码里
- token 放 URL 查询参数，被日志泄露
- refresh token 无限期且不轮换
- 前端把 token 打印到控制台
