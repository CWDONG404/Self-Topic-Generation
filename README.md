# 知题 StudyForge

知题是一个面向个人自托管场景的 AI 文档出题与练习平台。它可以把 PDF、DOCX、Markdown、TXT 资料整理为带出处的四选一题库，并通过“考点蓝图 → 出题 → 独立审题 → 返修/补题”的流程生成模拟卷。

## 主要能力

- 上传并持久化管理备考资料，区分“重点/考试大纲”和“权威正文材料”。
- 解析文本、扫描页、表格和文档内图片；PDF 引用保留页码及坐标。
- 支持 OpenAI 兼容接口与 Ollama，本地模式不自动回退云端。
- 按文档设置出题百分比，生成 50、100 题或自定义题量。
- LangGraph 编排考点、出题和审题角色，确定性 Supervisor 负责配额、重试、去重与进度。
- 网站内练习、考试、自动判分、答案解析、错题回看与出处侧栏。
- PostgreSQL/pgvector、Redis/Celery 和文件卷均由 Docker Compose 管理。

## 快速开始

### 1. 准备配置

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，至少替换 `APP_SECRET`、`POSTGRES_PASSWORD`，并同步修改 `DATABASE_URL` 中的密码。

`.env.example` 默认启用清华 TUNA 的 Debian/PyPI 镜像以改善中国大陆首次构建速度。若所在网络访问官方源更快，可删除 `APT_MIRROR_ROOT`，并把 `PIP_INDEX_URL` 改为 `https://pypi.org/simple`。镜像地址均为 Docker 构建参数，不会写入运行时模型请求。

### 2. 启动

```powershell
docker compose up --build -d
```

启动完成后访问：

- 网站：<http://localhost:3000>
- API 文档：<http://localhost:8000/docs>
- 健康检查：<http://localhost:8000/health>

首次构建需要下载容器镜像和文档解析依赖；这些准备完成后，可以使用本地模型执行断网任务。
后端包含 Docling/OCR/视觉依赖，首次镜像明显大于普通 FastAPI 项目；Dockerfile 已启用 apt 重试和 BuildKit pip 缓存，中断后可直接重跑同一命令。

### 3. 配置模型

在“设置 → 模型配置”中新建配置：

- Compose 内的 Ollama：地址使用 `http://ollama:11434`。
- Windows 宿主机 Ollama：地址使用 `http://host.docker.internal:11434`。
- OpenAI 兼容接口：填写 Base URL、模型名和 API Key。

蓝图、出题、审题、视觉和 Embedding 可以选择不同模型。启用本地模式时，系统会拒绝任何云端配置。

## Ollama 运行方式

如果宿主机已经运行 Ollama，直接使用默认 Compose 配置即可。

也可以让 Compose 启动 Ollama：

```powershell
docker compose --profile ollama up -d ollama
docker compose exec ollama ollama pull qwen3:8b
docker compose exec ollama ollama pull qwen3-vl:4b
docker compose exec ollama ollama pull qwen3-embedding:0.6b
```

推荐的默认分工：

- `qwen3:8b`：考点蓝图、出题、审题，开启“结构化输出”。
- `qwen3-vl:4b`：视觉理解，开启“结构化输出”和“视觉理解”。
- `qwen3-embedding:0.6b`：向量检索，只开启“Embedding”。

三者下载量合计约 9.1 GB。设置页提供同样的下载命令，并可一键写入三条角色配置；模型文件仍需用户明确执行命令后才会下载。

NVIDIA GPU 环境：

```powershell
docker compose --profile ollama-gpu up --build -d
```

不要同时启用 `ollama` 与 `ollama-gpu` profile，它们使用同一个端口和模型卷。

## 使用流程

1. 创建资料库并上传材料。
2. 将串讲、考试大纲标为“重点资料”，将教材标为“正文材料”。
3. 等待解析完成，检查章节、OCR 或视觉能力警告。
4. 新建模拟卷，设置题量和每份正文材料的百分比。
5. 查看任务阶段、已通过题数、返修和补题进度。
6. 完成后直接练习，或先在题目复核页编辑、停用与复审。
7. 点击题目出处，在侧边打开原 PDF 页并查看高亮区域。

## 数据与安全

- 默认只监听本机 `127.0.0.1`，项目不含登录系统，不应直接暴露到公网。
- API Key 使用 `APP_SECRET` 加密，读取接口只返回掩码，不返回明文。
- 原文件、预览、模型缓存、数据库和 Redis 数据保存在 Docker named volumes 中。
- 文档版本不可原地覆盖，历史题目的出处不会因重新上传而漂移。
- 本地模式不会自动改用云端；缺少视觉模型时会明确排除视觉材料。
- 若希望整个部署永久禁止云端任务，可在 `.env` 中设置 `STRICT_LOCAL_MODE=true`。

## 备份与恢复

数据库备份：

```powershell
docker compose exec -T postgres pg_dump -U studyforge -d studyforge -Fc -f /tmp/studyforge.dump
docker compose cp postgres:/tmp/studyforge.dump .\studyforge.dump
```

应用文件保存在 `studyforge_application_data` 卷。停机后可使用 Docker Desktop 的卷备份能力，或将卷内容复制到安全位置。恢复时应同时恢复数据库与应用文件卷，避免引用记录和原文件不一致。

## 本地开发

- 后端位于 `backend/`，使用 FastAPI、SQLAlchemy、Celery 与 LangGraph。
- 前端位于 `frontend/`，使用 React、TypeScript、Vite 与 Tailwind CSS。
- 后端测试：在 `backend` 目录安装开发依赖后运行 `pytest`。
- 前端检查：在 `frontend` 目录运行 `npm install`、`npm run build`。

## 首版边界

- 支持 PDF、DOCX、Markdown、TXT；不支持旧式 DOC、PPTX 和独立图片题库。
- 只生成四选一单选题。
- 不包含多用户、移动 App、公开云托管和试卷导出。
- AI 审查只能降低错误率，不能替代必要的人工复核。
