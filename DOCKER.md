# Docker 部署指南

## 快速启动

### 1. 配置环境变量

复制示例配置并填写必要的 API keys：

```bash
cd insight-ai-agent
cp .env.example .env
```

编辑 `.env` 文件，至少需要配置：

```bash
# 必须配置 LLM API Key（至少一个）
DASHSCOPE_API_KEY=your_dashscope_key_here

# Spring Boot Backend 地址
# Docker 内部访问宿主机用 host.docker.internal
SPRING_BOOT_BASE_URL=http://host.docker.internal:8080

# 如果使用服务账号登录
SPRING_BOOT_DIFY_ACCOUNT=your_account
SPRING_BOOT_DIFY_PASSWORD=your_password
```

### 2. 启动所有服务

一键启动 AI Agent + PostgreSQL + Redis：

```bash
docker-compose up -d
```

### 3. 查看服务状态

```bash
# 查看所有容器状态
docker-compose ps

# 查看 AI Agent 日志
docker-compose logs -f ai-agent

# 查看所有服务日志
docker-compose logs -f
```

### 4. 测试服务

```bash
# 健康检查
curl http://localhost:5000/health

# 测试 API
curl http://localhost:5000/api/conversation \
  -H "Content-Type: application/json" \
  -d '{"teacherId": "1", "message": "你好"}'
```

## 服务地址

启动后，服务将在以下端口监听：

| 服务 | 端口 | 访问地址 |
|------|------|---------|
| AI Agent | 5000 | http://localhost:5000 |
| PostgreSQL | 5433 | localhost:5433 |
| Redis | 6379 | localhost:6379 |

## 常用命令

```bash
# 启动服务
docker-compose up -d

# 停止服务
docker-compose down

# 重启服务
docker-compose restart

# 重新构建并启动
docker-compose up -d --build

# 查看日志
docker-compose logs -f [service_name]

# 进入容器
docker-compose exec ai-agent bash

# 清理所有数据（⚠️ 会删除数据库）
docker-compose down -v
```

## 开发模式

如果需要在开发时实时看到代码变更，可以使用 volume 挂载：

```yaml
# 在 docker-compose.yml 的 ai-agent 服务下添加：
volumes:
  - .:/app
  - ./data:/app/data
  - ./logs:/app/logs
```

然后重启服务：

```bash
docker-compose up -d --build
```

## 故障排查

### AI Agent 启动失败

1. 检查日志：
   ```bash
   docker-compose logs ai-agent
   ```

2. 检查环境变量是否正确配置：
   ```bash
   docker-compose exec ai-agent env | grep -E "DASHSCOPE|SPRING_BOOT"
   ```

### 无法连接到 PostgreSQL

1. 检查 PostgreSQL 是否启动：
   ```bash
   docker-compose ps postgres
   ```

2. 测试连接：
   ```bash
   docker-compose exec postgres pg_isready -U insight -d insight_agent
   ```

### 无法连接到 Redis

1. 检查 Redis 是否启动：
   ```bash
   docker-compose ps redis
   ```

2. 测试连接：
   ```bash
   docker-compose exec redis redis-cli ping
   ```

### 无法连接到 Spring Boot Backend

如果 AI Agent 在 Docker 内无法访问宿主机的 Spring Boot（8080 端口）：

**Windows/Mac**:
- 使用 `host.docker.internal`（已在 docker-compose.yml 中配置）

**Linux**:
- 需要使用宿主机的实际 IP 地址，或者在 docker-compose.yml 中添加：
  ```yaml
  extra_hosts:
    - "host.docker.internal:host-gateway"
  ```

## 生产部署建议

1. **使用环境变量文件**：
   ```bash
   docker-compose --env-file .env.production up -d
   ```

2. **使用固定版本镜像**（修改 Dockerfile）：
   ```dockerfile
   FROM python:3.11.8-slim AS builder
   ```

3. **配置资源限制**（修改 docker-compose.yml）：
   ```yaml
   deploy:
     resources:
       limits:
         cpus: '2'
         memory: 4G
       reservations:
         cpus: '1'
         memory: 2G
   ```

4. **使用外部数据库**：
   - 注释掉 docker-compose.yml 中的 postgres 和 redis 服务
   - 在 .env 中配置外部数据库连接信息

5. **启用日志轮转**：
   ```yaml
   logging:
     driver: "json-file"
     options:
       max-size: "10m"
       max-file: "3"
   ```

## 更新服务

```bash
# 拉取最新代码
git pull

# 重新构建并启动
docker-compose up -d --build

# 查看启动日志
docker-compose logs -f ai-agent
```

## 备份与恢复

### 备份数据库

```bash
docker-compose exec postgres pg_dump -U insight insight_agent > backup.sql
```

### 恢复数据库

```bash
cat backup.sql | docker-compose exec -T postgres psql -U insight -d insight_agent
```

### 备份 Redis

```bash
docker-compose exec redis redis-cli SAVE
docker cp insight-ai-agent-redis:/data/dump.rdb ./redis-backup.rdb
```
