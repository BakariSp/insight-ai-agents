# RAG 与向量数据库架构方案

> **文档目的**: 定义文档解析、向量化存储、语义检索的完整架构，明确各层职责与数据归属
> **技术选型**: RAG-Anything（含 LightRAG）作为统一 RAG 引擎 + PostgreSQL pgvector 持久化
> **前置文档**: [ai-mcp-java-integration.md](./ai-mcp-java-integration.md) — AI-MCP 无状态原则
> **修订日期**: 2026-02-06 (v2: 确定 RAG-Anything + LightRAG + PostgreSQL 方案)

---

## 1. 问题背景

### 1.1 当前 RAG 系统的不足

**现状** (`services/rag_service.py`):
```
SimpleRAGStore
├── 纯关键词匹配（无语义理解）
├── 内存存储（重启即丢）
├── 不支持文档上传/解析
├── 无向量 Embedding
└── 3 个 Collection: official_corpus / school_assets / question_bank
```

**问题**:
1. ❌ 关键词匹配无法处理语义相似查询（如 "勾股定理" 和 "直角三角形边长关系"）
2. ❌ 内存存储无持久化，服务重启后知识库清空
3. ❌ 不支持 PDF/PPT/Excel 等文档上传和解析
4. ❌ 知识点只能从预置 JSON 文件加载，无法动态扩充

### 1.2 外部方案调研与选型

#### 候选方案对比

| 维度 | **RAG-Anything** | **LightRAG** | **RAGFlow** |
|------|-----------------|-------------|-------------|
| **本质** | LightRAG + 多模态解析层 | 知识图谱 + 向量混合检索引擎 | 全栈 RAG 平台（带 Web UI） |
| **集成方式** | `pip install raganything` | `pip install lightrag-hku` | Docker 服务集群（5+ 容器） |
| **文档解析** | ✅ MinerU/Docling (PDF/PPT/Excel/图片) | ❌ 纯文本输入，无解析能力 | ✅ DeepDoc (最强，含 TSR/DLR) |
| **知识图谱** | ✅ (通过底层 LightRAG) | ✅ **核心能力** | ✅ v0.9+ GraphRAG |
| **检索模式** | 6 种 (local/global/hybrid/mix...) | 6 种 (同左，原生支持) | BM25 + 向量 + Rerank |
| **多模态处理** | ✅ Image/Table/Equation Processor | ❌ 无 | ✅ OCR/TSR/DLR |
| **存储后端** | PostgreSQL + pgvector (通过 LightRAG) | PostgreSQL/Neo4j/Milvus/Qdrant | Elasticsearch + MySQL + MinIO |
| **MySQL 支持** | ❌ (PostgreSQL) | ❌ (PostgreSQL) | ✅ 原生 |
| **DashScope/Qwen** | ⚠️ 需适配 | ✅ OpenAI 兼容 | ✅ 原生支持 |
| **最小资源** | 2 核 / 4GB RAM | 2 核 / 4GB RAM | **4+ 核 / 16GB+ RAM** |
| **部署复杂度** | 低 (pip install) | 低 (pip install) | **高** (ES + MySQL + MinIO + Redis) |

#### 关键发现：RAG-Anything 就是 LightRAG + 多模态

```
RAG-Anything 的依赖关系:
┌─────────────────────────────────┐
│         RAG-Anything            │  ← pip install raganything
│  ┌───────────────────────────┐  │
│  │  多模态解析层              │  │
│  │  ├── MinerU (PDF 解析)    │  │
│  │  ├── Docling (PPT/Word)   │  │
│  │  ├── ImageProcessor       │  │
│  │  ├── TableProcessor       │  │
│  │  └── EquationProcessor    │  │
│  └───────────┬───────────────┘  │
│              ↓                   │
│  ┌───────────────────────────┐  │
│  │  LightRAG (lightrag-hku)  │  │  ← 自动安装为依赖
│  │  ├── 知识图谱构建          │  │
│  │  ├── 6 种检索模式         │  │
│  │  ├── 实体/关系提取        │  │
│  │  └── 向量 + 图谱混合检索  │  │
│  └───────────────────────────┘  │
└─────────────────────────────────┘
```

**不需要二选一**：安装 RAG-Anything 就同时拥有 LightRAG 的全部检索能力 + 多模态文档解析。

#### 选型结论

| 方案 | 决定 | 理由 |
|------|------|------|
| **RAG-Anything** | ✅ **采用** | 一个包解决：多模态解析 + 知识图谱 + 向量检索 |
| **LightRAG** | ✅ 随 RAG-Anything 自动引入 | 底层检索引擎，不需要单独安装 |
| **RAGFlow** | ❌ 不采用 | 太重（5+ 容器/16GB RAM），是独立平台无法嵌入我们的 FastAPI，与 Agent 架构重叠 |

#### 其他参考

**Nanobot** ([github.com/BakariSp/nanobot](https://github.com/BakariSp/nanobot))：超轻量 AI Agent 框架。Tool 系统与我们的 FastMCP 方案能力相当，无直接集成价值。可参考其双层记忆（Daily Notes + Long-term Memory）和消息总线模式。

---

## 2. 架构设计

### 2.1 核心原则

延续 [ai-mcp-java-integration.md](./ai-mcp-java-integration.md) 的无状态原则，但对 RAG 做精确化：

```
AI-MCP 不持久化"用户业务数据"（App/Blueprint/Execution）
AI-MCP 可以管理"知识索引数据"（chunks/embeddings/knowledge graph）
Java 后端管鉴权 + 管业务数据 + 管原始文件 + 管权限
```

**为什么知识索引放 AI-MCP 侧？**
- 向量检索 + 知识图谱查询是 AI 的核心能力，不应跨网络调用 Java
- LightRAG 原生支持 PostgreSQL + pgvector，自带高效 ANN 索引
- 避免 Java 团队做不擅长的向量检索实现
- 权限控制通过 `teacher_id` workspace 隔离实现

数据分三层：

| 数据类型 | 归属 | 存储位置 | 示例 |
|----------|------|----------|------|
| **业务数据** | teacherId | Java MySQL + OSS | App, Blueprint, Execution, 原始文件 |
| **公共知识索引** | 系统级 | AI-MCP PostgreSQL (LightRAG) | DSE 课程大纲、公共题库、评分标准 |
| **用户知识索引** | teacherId | AI-MCP PostgreSQL (LightRAG, workspace 隔离) | 教师上传文档的 chunks/embeddings/entities |

### 2.2 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                         前端（React）                         │
│  1. 上传文件 → Java 后端                                      │
│  2. 发送 prompt → AI-MCP                                     │
│  3. 渲染 Page → 从 OSS 下载                                   │
└───────────────────────────┬─────────────────────────────────┘
                            │ JWT
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                    AI-MCP（Python FastAPI）                    │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ PlannerAgent │  │ExecutorAgent │  │  RAG-Anything     │   │
│  │ prompt→BP    │  │ BP→Page      │  │  (解析+检索一体)   │   │
│  └──────┬───────┘  └──────────────┘  └────────┬─────────┘   │
│         │                                      │             │
│  ┌──────┴──────────────────────────────────────┴─────────┐   │
│  │           RAG-Anything (统一 RAG 引擎)                   │   │
│  │                                                         │   │
│  │  多模态解析层:                                            │   │
│  │  ├── MinerU (PDF → text + tables + images + equations)  │   │
│  │  ├── Docling (PPT/Word → text + images)                 │   │
│  │  ├── ImageProcessor (图片 → OCR/Vision 分析)             │   │
│  │  ├── TableProcessor (表格 → 结构化数据)                   │   │
│  │  └── EquationProcessor (公式 → LaTeX 语义化)             │   │
│  │                                                         │   │
│  │  LightRAG 检索层:                                        │   │
│  │  ├── 知识图谱构建 (实体 + 关系自动提取)                    │   │
│  │  ├── 6 种检索模式 (local/global/hybrid/mix...)           │   │
│  │  └── 向量 + 图谱混合检索                                  │   │
│  └─────────────────────────┬───────────────────────────────┘   │
│                            │                                    │
│  ┌─────────────────────────┴───────────────────────────────┐   │
│  │  PostgreSQL + pgvector (AI-MCP 侧，LightRAG 管理)        │   │
│  │  ├── 公共知识库 workspace (系统级，只读)                    │   │
│  │  └── 用户知识库 workspace (按 teacher_id 隔离)             │   │
│  └─────────────────────────────────────────────────────────┘   │
└───────────────────────────┬─────────────────────────────────┘
                            │ JWT (透传)
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                   Java 后端（Spring Boot）                     │
│                                                              │
│  ┌──────────┐  ┌───────────┐  ┌────────────────────────┐   │
│  │ 鉴权中心  │  │  OSS 管理  │  │ 业务数据管理            │   │
│  │ JWT→tid  │  │ 上传/签名  │  │ App/BP/Exec/文件元数据  │   │
│  └──────────┘  └───────────┘  └────────────────────────┘   │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                        存储层                                 │
│  ┌──────────────┐  ┌──────────┐  ┌──────────────────────┐  │
│  │ MySQL (Java)  │  │ OSS      │  │ PostgreSQL (AI-MCP)  │  │
│  │ 业务元数据    │  │ 原始文件  │  │ pgvector 向量索引     │  │
│  │ App/BP/Exec  │  │ PDF/PPT  │  │ LightRAG 知识图谱     │  │
│  │ 文件元数据    │  │ 图片     │  │ chunks/entities       │  │
│  └──────────────┘  └──────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 2.3 存储职责划分

```
MySQL (Java 后端管理):
├── ai_apps             — App 元数据
├── ai_blueprints       — Blueprint 版本
├── ai_page_executions  — 执行记录 (Page URL)
├── ai_files            — 文件元数据 + parse_status
├── ai_app_shares       — 分享权限
└── 不存 chunks/embeddings/knowledge graph

PostgreSQL + pgvector (AI-MCP 侧，LightRAG 自动管理):
├── lightrag_doc_chunks     — 文档块 + 向量 (LightRAG 内部表)
├── lightrag_doc_full       — 完整文档 KV
├── lightrag_vdb_*          — 向量索引 (pgvector HNSW)
├── lightrag_graph_*        — 知识图谱 (实体 + 关系)
└── 按 working_dir 隔离 workspace (public / teacher-xxx)

OSS (Java 后端管理):
├── files/              — 用户上传的原始文件 (PDF/PPT/图片)
├── executions/         — Page JSON / dataContext
└── knowledge-base/     — 系统级素材
```

---

## 3. 向量数据库选型

### 3.1 最终选型：PostgreSQL + pgvector（LightRAG 原生支持）

之前的方案考虑了 MySQL 自建向量检索，但调研 LightRAG 后发现更优路径：

| 方案 | 技术 | 优势 | 劣势 | 决定 |
|------|------|------|------|------|
| **A: Java MySQL 自建** | MySQL + JSON 存 embedding + Java cosine | 零新增组件 | 无 ANN 索引，Java 团队需实现检索逻辑，> 10 万条不可用 | ❌ 放弃 |
| **B: PostgreSQL + pgvector** | LightRAG 原生后端 | LightRAG 全自动管理表结构/索引/检索，HNSW ANN 索引 | 多一个 PostgreSQL 实例 | ✅ **采用** |
| **C: 独立向量 DB** | Milvus / Qdrant | 专业 ANN，百万级毫秒检索 | 多一个服务，LightRAG 也支持 | ⚠️ Phase 3 备选 |

**选择 B 的理由**:
1. **LightRAG 自动管理一切**: 建表、建索引、CRUD、检索 — Java 团队零工作量
2. **HNSW 索引**: pgvector 支持 HNSW（近似最近邻），百万级数据毫秒级检索
3. **不需要自建 cosine similarity**: LightRAG 内部已实现高效检索
4. **PostgreSQL 运维成熟**: 比 Milvus/Qdrant 更简单，云厂商都有托管服务
5. **与 MySQL 共存不冲突**: MySQL 管业务数据，PostgreSQL 管知识索引，职责清晰

### 3.2 存储架构

```
Java 团队不需要碰向量存储
AI-MCP 侧 PostgreSQL 由 LightRAG 自动管理

PostgreSQL (AI-MCP 侧)
├── pgvector 扩展 (CREATE EXTENSION vector)
├── LightRAG 自动创建的表:
│   ├── lightrag_doc_full       — 完整文档 KV 存储
│   ├── lightrag_doc_chunks     — 文档块 + embedding (vector 类型)
│   ├── lightrag_vdb_entity     — 实体向量索引 (HNSW)
│   ├── lightrag_vdb_relation   — 关系向量索引 (HNSW)
│   ├── lightrag_vdb_chunks     — 块向量索引 (HNSW)
│   ├── lightrag_graph_nodes    — 知识图谱节点
│   └── lightrag_graph_edges    — 知识图谱边
└── workspace 隔离:
    ├── public/     — 系统公共知识库
    ├── teacher-001/ — 教师 001 的知识库
    └── teacher-002/ — 教师 002 的知识库
```

### 3.3 LightRAG PostgreSQL 配置

```python
from lightrag import LightRAG

# AI-MCP 启动时初始化
rag = LightRAG(
    working_dir=f"./workspaces/{teacher_id}",  # workspace 隔离
    llm_model_func=dashscope_complete,          # 复用现有 DashScope
    embedding_func=dashscope_embedding,          # text-embedding-v3

    # PostgreSQL + pgvector 存储
    kv_storage="PostgreSQLStorage",
    vector_storage="PGVectorStorage",
    graph_storage="PostgreSQLStorage",

    # 连接配置
    addon_params={
        "uri": "postgresql://lightrag:password@localhost:5432/lightrag_db",
        "vector_index": "HNSW",    # ANN 索引类型
        "hnsw_m": 16,              # HNSW 参数
        "hnsw_ef": 64,
    },

    # 模型配置
    embedding_dim=1024,             # DashScope text-embedding-v3
    max_token_size=8192,
)

await rag.initialize_storages()
```

### 3.4 性能预估（pgvector HNSW）

| 数据规模 | 检索延迟 | 是否可接受 | 对比 MySQL 方案 |
|----------|---------|-----------|----------------|
| < 1 万 chunks | < 10ms | ✅ | MySQL: ~100ms |
| 1-10 万 chunks | < 20ms | ✅ | MySQL: 100-500ms |
| 10-100 万 chunks | < 50ms | ✅ | MySQL: > 1s (不可用) |
| > 100 万 chunks | < 100ms | ⚠️ 可考虑 Milvus | MySQL: 完全不可用 |

### 3.5 PostgreSQL 部署

**开发环境** (Docker):
```bash
docker run -d \
  --name lightrag-pg \
  -e POSTGRES_DB=lightrag_db \
  -e POSTGRES_USER=lightrag \
  -e POSTGRES_PASSWORD=lightrag_dev \
  -p 5433:5432 \
  pgvector/pgvector:pg16
```

**生产环境**: 阿里云 RDS PostgreSQL（自带 pgvector 扩展）或 AWS RDS PostgreSQL。

**资源需求**: 2 核 / 4GB RAM / 20GB 磁盘（初期足够）

---

## 4. 文档解析管线

### 4.1 解析流程总览

```
教师上传 PDF/PPT/Excel
        ↓
   Java 后端接收
   ├── 1. 验证 JWT + 文件类型/大小
   ├── 2. 原始文件 → OSS (file_id)
   ├── 3. 文件元数据 → MySQL (ai_files 表)
   └── 4. 异步调用 AI-MCP 解析
               ↓
         AI-MCP 解析服务
         ├── 5. 从 OSS 下载文件 (signed URL)
         ├── 6. RAG-Anything 解析
         │     ├── PDF → MinerU → text + images + tables + equations
         │     ├── PPT → Docling → text + images
         │     ├── Excel → 结构化数据提取
         │     └── 图片 → OCR (Vision API)
         ├── 7. 分块 (chunking)
         ├── 8. 生成 Embedding (text-embedding 模型)
         ├── 9. 提取实体 + 关系 (LLM)
         └── 10. 回写 Java 后端
                    ↓
              Java 后端存储
              ├── 11. chunks + embeddings → ai_document_chunks
              ├── 12. entities → ai_document_entities
              ├── 13. relations → ai_entity_relations
              └── 14. 更新 ai_files.parse_status = 'completed'
```

### 4.2 AI-MCP 端：使用 RAG-Anything 直接处理

RAG-Anything 内部已封装了完整的 解析 → 分块 → 向量化 → 知识图谱构建 流程，
不需要我们自建 DocumentParser — 直接调用 RAG-Anything 的 `process_document()`。

```python
# services/rag_engine.py
# 统一 RAG 引擎：基于 RAG-Anything（含 LightRAG）

from raganything import RAGAnything, RAGAnythingConfig
from lightrag import LightRAG
from lightrag.utils import EmbeddingFunc
import httpx


class InsightRAGEngine:
    """
    统一 RAG 引擎

    封装 RAG-Anything，提供：
    1. 文档解析 + 自动入库（PDF/PPT/Excel/图片）
    2. 语义检索（向量 + 知识图谱混合）
    3. 多租户 workspace 隔离

    存储：PostgreSQL + pgvector（LightRAG 自动管理）
    """

    def __init__(self, pg_uri: str, dashscope_api_key: str):
        self.pg_uri = pg_uri
        self.dashscope_api_key = dashscope_api_key
        self._instances: dict[str, RAGAnything] = {}  # workspace_id → RAGAnything

    async def get_instance(self, workspace_id: str) -> RAGAnything:
        """
        获取指定 workspace 的 RAGAnything 实例
        workspace_id: "public" 或 "teacher-{teacherId}"
        """
        if workspace_id not in self._instances:
            config = RAGAnythingConfig(
                working_dir=f"./workspaces/{workspace_id}",
                parser="mineru",              # MinerU 用于 PDF
                process_images=True,          # 启用图片处理
                process_tables=True,          # 启用表格处理
                process_equations=True,       # 启用公式处理
            )

            rag = RAGAnything(
                config=config,
                rag=LightRAG(
                    working_dir=f"./workspaces/{workspace_id}",
                    llm_model_func=self._dashscope_llm,
                    embedding_func=EmbeddingFunc(
                        func=self._dashscope_embedding,
                        embedding_dim=1024,
                        max_token_size=8192,
                    ),
                    # PostgreSQL 存储
                    kv_storage="PostgreSQLStorage",
                    vector_storage="PGVectorStorage",
                    graph_storage="PostgreSQLStorage",
                    addon_params={
                        "uri": self.pg_uri,
                        "vector_index": "HNSW",
                    },
                ),
                vlm_func=self._qwen_vl,       # Qwen-VL 用于图片分析
            )
            self._instances[workspace_id] = rag

        return self._instances[workspace_id]

    async def ingest_document(
        self,
        teacher_id: str,
        file_path: str,
    ) -> dict:
        """
        解析文档并入库（RAG-Anything 一步到位）

        RAG-Anything 内部自动完成:
        1. MinerU/Docling 解析文档 → text + tables + images + equations
        2. 多模态处理器分析每种内容 → 结构化描述
        3. LightRAG 提取实体 + 关系 → 知识图谱
        4. Embedding 生成 → pgvector 存储
        5. 全部持久化到 PostgreSQL

        我们只需要一行调用。
        """
        rag = await self.get_instance(f"teacher-{teacher_id}")
        await rag.process_document(file_path)
        return {"status": "completed"}

    async def search(
        self,
        teacher_id: str,
        query: str,
        mode: str = "hybrid",
        top_k: int = 10,
        include_public: bool = True,
    ) -> list[dict]:
        """
        混合检索：用户 workspace + 公共 workspace

        LightRAG 6 种检索模式:
        - "local": 局部实体关系
        - "global": 全局知识图谱概览
        - "hybrid": local + global（推荐）
        - "naive": 纯向量相似度
        - "mix": 向量 + 图谱 + rerank（最高质量）
        - "bypass": 跳过检索
        """
        results = []

        # 1. 用户知识库检索
        user_rag = await self.get_instance(f"teacher-{teacher_id}")
        user_result = await user_rag.rag.aquery(query, param=QueryParam(mode=mode))
        results.append({"source": "user", "content": user_result})

        # 2. 公共知识库检索
        if include_public:
            public_rag = await self.get_instance("public")
            public_result = await public_rag.rag.aquery(query, param=QueryParam(mode=mode))
            results.append({"source": "public", "content": public_result})

        return results

    async def _dashscope_llm(self, prompt, **kwargs):
        """DashScope Qwen LLM 调用"""
        ...

    async def _dashscope_embedding(self, texts: list[str]):
        """DashScope text-embedding-v3"""
        ...

    async def _qwen_vl(self, image_path: str, prompt: str):
        """Qwen-VL 图片分析（用于多模态处理）"""
        ...
```

**关键点**: 不需要自建 DocumentParser。RAG-Anything 的 `process_document()` 一步完成：
解析 → 分块 → 多模态处理 → Embedding → 知识图谱 → 持久化。我们只需管 workspace 隔离。

### 4.3 Embedding 模型选择

| 模型 | 维度 | 提供商 | 中文能力 | 成本 | 推荐 |
|------|------|--------|---------|------|------|
| text-embedding-v3 | 1024 | DashScope (阿里) | ✅ 优秀 | ¥0.0007/千 tokens | ✅ 首选 |
| text-embedding-3-small | 1536 | OpenAI | ⚠️ 一般 | $0.02/M tokens | 备选 |
| bge-large-zh-v1.5 | 1024 | 开源 (BAAI) | ✅ 优秀 | 免费（自部署） | Phase 2 考虑 |

**推荐**: DashScope text-embedding-v3，与现有 LLM 调用（Qwen）共用阿里云账号，中文效果好。

### 4.4 文件类型与解析能力

| 文件类型 | 解析引擎 | 提取内容 | AI 分析能力 |
|----------|---------|---------|------------|
| **PDF** | MinerU | 文本 + 图片 + 表格 + 公式 | ✅ 全量分析 |
| **PPT/PPTX** | Docling (→ PDF → MinerU) | 文本 + 图片 | ✅ 文本分析，图片 OCR |
| **Excel/XLSX** | openpyxl 直接解析 | 结构化数据 | ✅ 数据提取 + 分析 |
| **图片** | Vision API (GPT-4o / Qwen-VL) | OCR + 内容理解 | ✅ OCR + 视觉分析 |
| **Word/DOCX** | Docling | 文本 + 表格 | ✅ 文本分析 |

---

## 5. 数据流详解

### 5.1 场景 1: 教师上传教案 PDF → 解析入库

```
步骤 1: 前端上传文件
  POST /api/studio/teacher/me/files/upload
  Headers: Authorization: Bearer <JWT>
  Body: { file: <PDF>, purpose: "rag_material", title: "二次函数教案" }

  → Java 后端:
    1. 验证 JWT → teacherId
    2. 验证文件类型/大小 (PDF ≤ 50MB)
    3. 上传原始文件 → OSS
    4. 存元数据 → ai_files 表 (parse_status = 'pending')
    5. 返回 { fileId: "file-xxx" }

步骤 2: 触发异步解析
  Java 后端异步调用 AI-MCP:
  POST /api/internal/documents/parse    ← AI-MCP 内部端点
  Headers: Authorization: Bearer <JWT>  ← 透传用户 JWT
  Body: {
    "fileId": "file-xxx",
    "collection": "rag_material",
    "parseOptions": {
      "parseMethod": "auto",
      "processImages": true,
      "processTables": true,
      "processEquations": true
    }
  }

步骤 3: AI-MCP 处理（RAG-Anything 一步完成）
  → AI-MCP:
    1. 从 Java 获取 signed URL，下载 PDF
    2. RAG-Anything.process_document() 一步完成:
       ├── MinerU 解析 PDF → text + tables + images + equations
       ├── TableProcessor → 表格结构化
       ├── ImageProcessor → 图片 OCR/视觉分析 (Qwen-VL)
       ├── EquationProcessor → 公式 LaTeX 语义化
       ├── 分块 + DashScope Embedding → 向量
       ├── LLM 自动提取实体 + 关系 → 知识图谱
       └── 全部写入 PostgreSQL + pgvector (LightRAG 自动管理)
    3. 通知 Java 后端更新解析状态

步骤 4: 更新 Java 文件状态
  AI-MCP 回调 Java:
  PUT /api/studio/teacher/me/files/{fileId}/parse-status
  Headers: Authorization: Bearer <JWT>
  Body: {
    "parseStatus": "completed",
    "chunkCount": 15,
    "entityCount": 8,
  }

  → Java 后端:
    UPDATE ai_files SET parse_status = 'completed',
      chunk_count = 15, entity_count = 8
    WHERE file_id = 'file-xxx'
```

**关键简化**:
- ✅ 不需要 Java 端建 chunks/entities/relations 表
- ✅ 不需要 Java 端实现向量检索逻辑
- ✅ RAG-Anything + LightRAG + PostgreSQL 自动管理全部知识索引
- ✅ Java 只需要管文件元数据和 parse_status

### 5.2 场景 2: PlannerAgent 检索相关知识

```
用户: "帮我做一个二次函数的复习练习"
        ↓
  AI-MCP PlannerAgent:
    1. 调用 InsightRAGEngine.search()
       → 内部自动完成:

    2. 用户知识库检索 (LightRAG hybrid 模式):
       workspace: "teacher-{teacherId}"
       ├── 向量相似度搜索 (pgvector HNSW)
       ├── 知识图谱遍历 (二次函数 → 前置: 一次函数, 关联: 顶点公式)
       └── 合并排序

    3. 公共知识库检索 (LightRAG hybrid 模式):
       workspace: "public"
       ├── DSE 数学课程大纲中"二次函数"相关内容
       └── 公共题库中的类似题目

    4. 合并结果:
       [
         { content: "二次函数的一般形式...", source: "user/教案.pdf" },
         { content: "DSE 数学 Unit 3: 二次函数...", source: "public/dse-math" },
         { content: "二次函数练习题: 1. ...", source: "user/题库" },
         ...
       ]

    5. PlannerAgent 结合检索结果生成 Blueprint:
       - Blueprint 中引用检索到的知识点
       - 生成练习题时参考题库中的类似题目
       - 知识图谱提供前置知识链（一次函数 → 二次函数 → 顶点公式）
```

**关键**: 全部在 AI-MCP 侧完成，不需要调用 Java API 做检索。Java 只在上传/鉴权时参与。

### 5.3 场景 3: 上传成绩截图 → OCR → 数据分析

```
用户上传: exam_scores.png + prompt: "分析这个成绩表"
        ↓
  AI-MCP:
    1. 从 Java 获取图片 signed URL
    2. Vision API (Qwen-VL) OCR:
       → 识别为成绩表格
       → 结构化: [{name, score, rank}, ...]
    3. 数据不入向量库（一次性分析，非知识库素材）
    4. 直接传给 PlannerAgent 作为上下文
    5. 生成 Blueprint → ExecutorAgent → Page
    6. 回写 Java 后端 (Page + dataContext)
```

---

## 6. Java 后端变更（大幅简化）

采用 RAG-Anything + LightRAG + PostgreSQL 方案后，**Java 后端不再需要处理向量存储和检索**。

### 6.1 Java 只需要做的事

| 职责 | 端点 | 说明 |
|------|------|------|
| 文件上传 | `POST .../files/upload` | 已有（ai-mcp-java-integration.md Section 10） |
| 文件元数据 | `GET .../files/{fileId}` | 已有 |
| 文件下载 URL | `GET .../files/{fileId}/download` | 已有（签名 URL） |
| **更新解析状态** | `PUT .../files/{fileId}/parse-status` | **新增**（轻量） |

### 6.2 新增端点：更新解析状态

**端点**: `PUT /api/studio/teacher/me/files/{fileId}/parse-status`

AI-MCP 完成 RAG-Anything 解析后回调此端点更新状态。

**请求体**:
```json
{
  "parseStatus": "completed",
  "chunkCount": 15,
  "entityCount": 8,
  "parseError": null
}
```

**返回结果**:
```json
{
  "code": 200,
  "data": {
    "fileId": "file-xxx",
    "parseStatus": "completed"
  }
}
```

**Java 实现**:
```java
@PutMapping("/api/studio/teacher/me/files/{fileId}/parse-status")
public ResponseEntity<?> updateParseStatus(
    @RequestHeader("Authorization") String authHeader,
    @PathVariable String fileId,
    @RequestBody UpdateParseStatusRequest request
) {
    String teacherId = jwtService.extractTeacherId(authHeader);

    // 验证文件归属
    FileMetadata file = fileRepository.findByFileId(fileId)
        .orElseThrow(() -> new NotFoundException("File not found"));
    if (!file.getTeacherId().equals(teacherId)) {
        throw new ForbiddenException("Not file owner");
    }

    // 更新状态
    file.setParseStatus(request.getParseStatus());
    file.setChunkCount(request.getChunkCount());
    file.setEntityCount(request.getEntityCount());
    file.setParseError(request.getParseError());
    file.setParsedAt(Instant.now());
    fileRepository.save(file);

    return ResponseEntity.ok(Map.of("fileId", fileId, "parseStatus", request.getParseStatus()));
}
```

### 6.3 Java 不再需要做的事

| 原方案 | 现状 | 原因 |
|--------|------|------|
| ~~`ai_document_chunks` 表~~ | ❌ 移除 | LightRAG 自动管理 PostgreSQL |
| ~~`ai_document_entities` 表~~ | ❌ 移除 | LightRAG 自动管理知识图谱 |
| ~~`ai_entity_relations` 表~~ | ❌ 移除 | LightRAG 自动管理 |
| ~~`POST .../files/{fileId}/parsed`~~ | ❌ 移除 | chunks 直接存 PostgreSQL |
| ~~`POST .../knowledge/search`~~ | ❌ 移除 | 检索在 AI-MCP 侧完成 |
| ~~`VectorSearchService`~~ | ❌ 移除 | 不需要 Java 做 cosine similarity |

**Java 团队工作量从"大量"降到"一个轻量 PUT 端点"。**

---

## 7. 公共知识库

### 7.1 设计

DSE 课程大纲、评分标准、公共题库使用独立的 LightRAG workspace：

```python
# 公共知识库初始化（服务启动时执行一次）
public_rag = await rag_engine.get_instance("public")

# 导入已有知识点 JSON → LightRAG 知识图谱
for kp_file in glob("data/knowledge_points/dse-*.json"):
    await public_rag.rag.ainsert(open(kp_file).read())

# 导入评分标准
for rubric_file in glob("data/rubrics/*.json"):
    await public_rag.rag.ainsert(open(rubric_file).read())

# 后续导入 DSE 课程 PDF（RAG-Anything 多模态解析）
await public_rag.process_document("data/curriculum/dse-math-syllabus.pdf")
```

**特点**:
- workspace = "public"，与用户 workspace 隔离
- 共用同一个 PostgreSQL 实例，不同 working_dir
- 只读（运行时不接受用户写入，管理员脚本更新）
- 已有 `data/knowledge_points/` 和 `data/rubrics/` 自动导入

### 7.2 检索合并

见 Section 4.2 `InsightRAGEngine.search()` — 自动合并公共 + 用户 workspace 结果。

---

## 8. ai_files 表扩展

在 [ai-mcp-java-integration.md](./ai-mcp-java-integration.md) Section 10.5 的 `ai_files` 表基础上新增解析相关字段：

```sql
ALTER TABLE ai_files ADD COLUMN parse_status VARCHAR(20)
    DEFAULT NULL
    COMMENT '解析状态: pending / processing / completed / failed';

ALTER TABLE ai_files ADD COLUMN parse_error TEXT
    DEFAULT NULL
    COMMENT '解析错误信息';

ALTER TABLE ai_files ADD COLUMN chunk_count INT
    DEFAULT 0
    COMMENT '解析后的 chunk 数量';

ALTER TABLE ai_files ADD COLUMN entity_count INT
    DEFAULT 0
    COMMENT '提取的实体数量';

ALTER TABLE ai_files ADD COLUMN parsed_at TIMESTAMP
    DEFAULT NULL
    COMMENT '解析完成时间';
```

**解析状态流转**:
```
上传完成 → pending → processing → completed
                         ↓
                       failed (可重试)
```

---

## 9. 实施路线图

### Phase 1: RAG 引擎集成（P0）

**目标**: 用 RAG-Anything 替换 SimpleRAGStore，实现语义检索 + 文档解析

**基础设施**:
- [ ] 部署 PostgreSQL + pgvector (Docker)
- [ ] `pip install raganything` (含 lightrag-hku)
- [ ] 配置 `.env`: PG 连接串 + DashScope API Key

**AI-MCP 端**:
- [ ] `services/rag_engine.py` — InsightRAGEngine（封装 RAG-Anything）
- [ ] `services/embedding_service.py` — DashScope text-embedding-v3
- [ ] `POST /api/internal/documents/parse` — 文档解析端点
- [ ] 改造 `services/rag_service.py` → 调用 InsightRAGEngine
- [ ] 公共知识库初始化（导入现有 knowledge_points/ + rubrics/）

**Java 后端**（极少改动）:
- [ ] `ai_files` 表增加 `parse_status` 等字段
- [ ] `PUT .../files/{fileId}/parse-status` — 轻量回调端点

**验证标准**:
- 上传 PDF → RAG-Anything 解析 → chunks 入 PostgreSQL
- 语义查询 "二次函数" → 返回相关内容（知识图谱 + 向量混合）
- 公共知识库 + 用户知识库混合检索
- 现有 PlannerAgent 能使用检索结果生成 Blueprint

### Phase 2: 多模态深度解析（P1）

**AI-MCP 端**:
- [ ] 集成 MinerU 完整版（PDF 深度解析: 表格/图片/公式）
- [ ] 集成 Docling（PPT/Word/Excel 解析）
- [ ] Qwen-VL 视觉分析（成绩截图 OCR → 结构化数据）
- [ ] 批量文档导入（历年试卷、课程 PDF）
- [ ] RAG-Anything 上下文感知配置优化

### Phase 3: 检索质量优化（P2）

- [ ] Reranker 集成（DashScope gte-rerank-v2）
- [ ] 检索模式调优（不同场景用不同 mode: hybrid vs mix）
- [ ] LightRAG 实体类型定制（教育领域: knowledge_point, formula, concept）
- [ ] 当 pgvector 不够时迁移到 Milvus（LightRAG 原生支持，改配置即可）
- [ ] 缓存策略（热门查询 + Embedding 缓存）

---

## 10. 与现有文档的关系

### 不变的部分

- **业务数据归属**: App/Blueprint/Execution → Java MySQL（teacherId 从 JWT）
- **原始文件管理**: OSS 由 Java 后端统一管理（签名 URL）
- **大文件上传流程**: 前端 → Java 上传 → 返回 file_id → AI-MCP 按需拉取
- **JWT 透传机制**: AI-MCP 调用 Java API 时透传 JWT

### 调整的部分

| 原方案 | 新方案 | 原因 |
|--------|--------|------|
| AI-MCP 完全无状态 | AI-MCP 管理知识索引（PostgreSQL） | 知识检索是 AI 核心能力 |
| 向量存储在 Java MySQL | 向量存储在 AI-MCP PostgreSQL (pgvector) | LightRAG 原生支持，HNSW 高效 |
| Java 建 3 张新表 | Java 只加 parse_status 字段 | Java 工作量大幅减少 |
| Java 实现向量检索 | AI-MCP LightRAG 自动检索 | 不需要 Java 做不擅长的事 |

### 新增的部分

- **RAG-Anything 引擎**: AI-MCP 侧统一的文档解析 + 知识图谱 + 语义检索
- **PostgreSQL + pgvector**: AI-MCP 侧新增数据库（LightRAG 自动管理）
- **Workspace 隔离**: 公共知识库 + 按 teacher_id 的用户知识库
- **ai_files 表扩展**: 增加 parse_status 等字段

### 相关文档

- [AI-MCP 与 Java 集成](./ai-mcp-java-integration.md) — 基础架构原则（本文档的前置）
- [存储优化方案](./storage-optimization-plan.md) — OSS 混合存储策略
- [系统架构全览](./system-architecture-overview.md) — 全场景数据流（含 RAG 素材管理）
- [Java 后端集成规范](./java-backend-spec.md) — API 端点设计

---

## 11. FAQ

### Q1: AI-MCP 管 PostgreSQL 不就违反"无状态"原则了吗？

**答**: 我们精确化了"无状态"的定义：

```
AI-MCP 不持久化 "用户业务数据"（App/Blueprint/Execution）   ← 不变
AI-MCP 可以管理 "知识索引数据"（chunks/embeddings/graph）    ← 新增
```

理由：
- 知识索引是 AI 检索能力的一部分，不是业务数据
- 向量检索 + 知识图谱查询必须在 AI 侧才高效（不应跨网络调 Java）
- LightRAG 原生管理 PostgreSQL，零额外开发
- 用户数据归属通过 workspace 隔离实现（`teacher-{teacherId}`）
- PostgreSQL 是持久化的，AI-MCP 重启不丢数据

### Q2: 为什么不用 MySQL 做向量检索？

**答**: LightRAG 不支持 MySQL（只支持 PostgreSQL + pgvector）。对比：

| 维度 | MySQL 自建 | PostgreSQL pgvector |
|------|-----------|-------------------|
| ANN 索引 | ❌ 无，暴力扫描 | ✅ HNSW（毫秒级） |
| 10 万条检索 | ~500ms | ~20ms |
| 开发工作量 | Java 团队手写 cosine | LightRAG 自动管理 |
| 知识图谱 | 需自建 3 张表 | LightRAG 自动管理 |

多一个 PostgreSQL 实例的运维成本远低于 Java 团队自建向量检索的开发成本。

### Q3: 为什么不用 RAGFlow？

**答**:

| 维度 | RAGFlow | 我们的选择 (RAG-Anything) |
|------|---------|--------------------------|
| 部署 | 5+ Docker 容器，16GB+ RAM | pip install，4GB RAM |
| 集成方式 | 独立平台，REST API | Python 库，直接嵌入 FastAPI |
| 与 Agent 关系 | 有自己的 Agent/对话系统 | 融入我们的 PlannerAgent/ExecutorAgent |
| 文档解析 | ✅ 最强（DeepDoc） | ✅ 足够（MinerU/Docling） |

RAGFlow 是一个完整的"RAG 平台"，我们需要的是"RAG 引擎组件"。

### Q4: RAG-Anything 和 LightRAG 是什么关系？

**答**:

```
RAG-Anything = LightRAG + 多模态解析
pip install raganything → 自动安装 lightrag-hku

我们用 RAG-Anything 调用:
├── process_document("file.pdf")  ← RAG-Anything 独有（多模态解析）
├── rag.aquery("二次函数")         ← LightRAG 原生（6 种检索模式）
└── rag.ainsert("纯文本内容")      ← LightRAG 原生（文本直接入库）
```

不需要二选一，一个包含另一个。

### Q5: 解析失败怎么办？

**答**:
```
1. AI-MCP 回调 Java: parse_status = 'failed'，记录 parse_error
2. 前端展示"解析失败"状态，提供"重试"按钮
3. 重试: Java 重新调 AI-MCP 解析端点
4. 最多重试 3 次，仍失败则需要人工介入
5. 原始文件始终保存在 OSS（不丢失）
```

### Q6: Embedding 模型更换时怎么办？

**答**: LightRAG workspace 级别管理 embedding 配置。更换模型时：
```
方案 A: 创建新 workspace，重新导入所有文档（推荐，干净）
方案 B: LightRAG 支持 re-embedding（遍历已有 chunks 重新向量化）
```

### Q7: PostgreSQL 和 MySQL 会冲突吗？

**答**: 不会。完全独立的两个数据库实例，职责不同：
```
MySQL (Java 管) → 业务数据，Java 团队熟悉
PostgreSQL (AI 管) → 知识索引，LightRAG 自动管理，Java 不碰
```
类似于同一个系统用 MySQL 存业务数据 + Redis 存缓存，各管各的。
