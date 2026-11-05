# Docker 镜像基础

## 镜像与容器

镜像是只读模板，容器是镜像的运行实例。镜像由多层组成，每条 Dockerfile 指令生成一层，层会被缓存复用。容器在镜像之上加一层可写层，删除容器不会影响镜像。

## Dockerfile 基本结构

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

先复制依赖文件再安装，最后复制源码，这样改代码不会让依赖层缓存失效。反过来先 COPY . 再 pip install，每次改一行代码都要重装依赖。

## 构建上下文与 .dockerignore

`docker build` 会把上下文目录发给守护进程。`venv`、`data`、`.git`、`node_modules` 会显著拖慢构建并泄露内容，必须写进 `.dockerignore`。

## 多阶段构建

编译依赖与运行依赖分离，最终镜像只保留运行所需产物：

```dockerfile
FROM python:3.12 AS builder
RUN pip wheel -r requirements.txt -w /wheels

FROM python:3.12-slim
COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels /wheels/*.whl
```

好处是镜像更小、攻击面更少。编译工具链不会进入运行镜像。

## 基础镜像选择

`slim` 比默认镜像小很多；`alpine` 更小但用 musl libc，某些二进制轮子不兼容，编译耗时长。对有 C 扩展的依赖，`slim` 通常更稳。

## 用户与权限

默认以 root 运行容器不安全。创建非 root 用户并切换：

```dockerfile
RUN useradd -m appuser
USER appuser
```

容器逃逸的风险会显著降低。文件权限要对应调整，避免只读目录写入失败。

## 端口与入口

`EXPOSE` 只是文档声明，不实际映射端口，运行时用 `-p 8000:8000`。`CMD` 是默认命令，`ENTRYPOINT` 是固定入口，两者组合时 CMD 作为参数传给 ENTRYPOINT。

## 健康检查

`HEALTHCHECK` 定期执行命令判断容器是否健康，编排系统依据它决定是否重启或摘流量。检查接口应轻量，避免依赖外部服务导致误判。

## 数据持久化

容器删除后可写层消失。数据库文件、上传文件必须挂载卷：

```bash
docker run -v ./data:/app/data myapp
```

不要把业务数据写进镜像，也不要在容器内做需要持久化的状态。

## 常见坑

- 镜像里带了 .env 与密钥
- 每次构建都重新装依赖
- 用 latest 标签导致环境不可复现
- 在容器里跑开发服务器并暴露公网
- 日志写到文件而不是 stdout，编排系统收不到
