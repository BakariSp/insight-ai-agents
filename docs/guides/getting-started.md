# 快速开始

> 从零启动 Insight AI Agent 服务。

---

## 环境要求

- Python 3.9+
- pip

---

## 安装步骤

```bash
# 克隆项目
git clone <repo-url>
cd insight-ai-agent

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env，填入你的 API Key
```

---

## 启动服务

### 当前 (Phase 0 — Flask)

```bash
python app.py
# 服务运行在 http://localhost:5000
```

### 目标 (Phase 1+ — FastAPI)

```bash
uvicorn main:app --reload --port 8000
# 服务运行在 http://localhost:8000
```

---

## 验证

```bash
# 健康检查
curl http://localhost:5000/health

# 测试对话
curl -X POST http://localhost:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "你好，介绍一下你自己"}'

# 查看可用模型
curl http://localhost:5000/models

# 查看可用技能
curl http://localhost:5000/skills
```

---

## 运行测试

```bash
pytest tests/ -v
```

---

## 下一步

- [环境变量说明](./environment.md) — 完整配置参考
- [添加新技能](./adding-skills.md) — 扩展 Agent 能力
- [架构总览](../architecture/overview.md) — 了解系统设计
