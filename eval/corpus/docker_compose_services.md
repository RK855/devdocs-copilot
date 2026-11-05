# Docker Compose 服务编排

## compose 的作用

Compose 用一个 YAML 文件描述多容器应用：网络、卷、环境变量、依赖关系。适合本地开发与小型部署，不适合大规模集群编排。

```yaml
services:
  api:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      - db
  db:
    image: postgres:16
    volumes:
      - pgdata:/var/lib/postgresql/data
volumes:
  pgdata:
```

## depends_on 不等于就绪

`depends_on` 只保证容器启动顺序，不保证内部服务已可用。数据库容器启动后还需要时间初始化，API 可能连接失败。解决方式：

- 在应用侧做带退避的连库重试
- 或用 `healthcheck` + `condition: service_healthy`

```yaml
depends_on:
  db:
    condition: service_healthy
```

## 网络与服务发现

同一 compose 项目内的服务默认在同一网络，可以用服务名做主机名。例如 API 连数据库写 `host=db`，而不是 localhost。容器内的 localhost 指向容器自己。

## 卷与环境变量

命名卷由 Docker 管理，适合数据持久化；绑定挂载 `./data:/app/data` 适合开发时热更新。环境变量可以用 `environment` 直接写，或 `env_file` 从文件读取。密钥不要写进 compose 文件并提交到仓库。

## 覆盖文件

`docker-compose.override.yml` 会自动与主文件合并，适合放开发专用配置（挂载源码、改端口、开调试）。生产用 `-f docker-compose.yml -f docker-compose.prod.yml` 显式指定。

## 常用命令

```bash
docker compose up -d        # 后台启动
docker compose logs -f api  # 跟随日志
docker compose exec api bash # 进入容器
docker compose down -v      # 停止并删除卷（会丢数据）
```

`down -v` 会删除命名卷，是危险命令，生产环境慎用。

## 资源限制

`deploy.resources.limits` 可以限制 CPU 与内存，防止单个服务拖垮宿主机。本地开发一般不需要，部署到共享机器时有用。

## 健康检查与重启策略

`restart: unless-stopped` 让服务异常退出后自动重启。配合健康检查，编排系统能在服务假死时重启容器。日志应输出到 stdout，由 Docker 收集，不要写文件。

## 常见坑

- 用 localhost 连其他容器
- 把数据库密码写进 YAML 并提交
- 只配 depends_on 就以为数据库可用
- 开发环境挂载覆盖了容器内的依赖目录
- 忘记 `down` 导致端口占用
