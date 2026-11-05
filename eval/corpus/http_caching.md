# HTTP 缓存机制

## 强缓存与协商缓存

HTTP 缓存分两层：强缓存和协商缓存。强缓存命中时浏览器直接用本地副本，不发请求。响应头 `Cache-Control: max-age=3600` 表示资源在 3600 秒内可直接复用；`no-cache` 表示每次都要向服务端确认，`no-store` 表示完全不缓存。`Expires` 是 `max-age` 的旧版写法，依赖客户端时钟，已被 `Cache-Control` 取代。

协商缓存每次都会发请求，但服务端可能只回 304 Not Modified，不带响应体。判断依据是 `ETag`/`If-None-Match` 或 `Last-Modified`/`If-Modified-Since`。`ETag` 更精确，能识别内容是否真的变化；`Last-Modified` 精度只到秒，且无法区分内容变化但时间未变的情况。

## 缓存策略选择

静态资源通常用强缓存加长 `max-age`，文件名带内容哈希（如 `app.3f2a1b.js`），内容一变文件名就变，可以放心设一年。接口数据更适合协商缓存或短 `max-age`，因为数据变化频繁，长缓存会导致用户看到过期内容。

用户私有数据必须加 `Cache-Control: private`，不能进 CDN 共享缓存；公共资源才用 `public`。带 `Vary` 头的响应要按维度缓存，例如 `Vary: Accept-Encoding` 表示压缩与非压缩版本分开存。

## 常见坑

- 对接口设置过长 `max-age`，数据更新后用户仍看到旧值
- 忘了 `Vary`，导致不同 `Accept-Encoding` 或语言返回错误版本
- 用 `no-store` 处理所有动态接口，缓存完全失效、后端压力陡增
- CDN 缓存了带登录态的响应，造成越权数据泄露
- 混淆 `no-cache` 与 `no-store`：前者可缓存但每次校验，后者禁止存储
