# 项目长期约定

## 选题与范围
- 毕设：基于大模型 API 的校园智能问答与办事指南系统。单校、桌面 Web，不接业务系统写接口，不取私有数据，模拟身份。
- 目标不是"像人"，是**办对率 / 拒答准确率 / 口径一致性**。

## 文档结构（现行，用户已重整目录）
- `docs/01-概要设计/`（原 01-设计方案，已改名）：`系统总体层次结构.md`（3 节：层次总览 + 图1、链路层次 + 图2、部署层次 + 图3）、`模块设计.md`（用户简化成只剩 1 模块总览 M1–M15 表 + 2 模块调用关系图；原「模块功能/调用清单/主链路」已删，别恢复）、`阶段计划.md`（P0–P7，16 周）。
- `docs/02-环境与依赖/环境需求与依赖.md`：1 环境总表、2 后端依赖（2.1 运行 / 2.2 开发）、3 前端依赖（3.1 运行 / 3.2 开发）。**不要新增章节**。
- `docs/03-详细设计/`：**按子系统 8 篇**，不按阶段。`01-数据模型` / `02-知识入库` / `03-检索与问答` / `04-模型网关` / `05-会话编排` / `06-接入控制` / `07-运营与评测` / `08-前端`。只写「小节 + 表格 + 参数实值」，不写阶段目标、不写注意事项、不写设计理由；同一事实只写一次（发布状态机在 02 §6，07 只放指针）。旧的 P0–P7 阶段文档用户已删，不要恢复。
- 图片：`docs/image/architecture/01-layers.png` … `06-module-flow.png`，阶段时间轴在 `docs/image/plan/01-timeline.png`。
- **图的源码在 `docs/image/architecture/src/`**：图 1 是 `01-layers.drawio`（draw.io 手排，为精确居中），其余 5 张是 `*.puml`。改 puml = 用 `.workbuddy/tmp/plantuml.jar` 渲染 → 覆盖同名 PNG（PNG 名默认取 `@startuml` 后的图名，需手动改名）。改 drawio = 导出覆盖 PNG。
- **draw.io 已装**：`C:\Users\19517\AppData\Local\Programs\draw.io\draw.io.exe`（32.5.5，winget 装的，不在 Program Files）。导出必须带 `--no-sandbox --disable-gpu`，否则报 `Renderer process gone`：
  `drawio.exe --no-sandbox --disable-gpu -x -f png -e -b 10 -s 2 -o out.png in.drawio`。
- 旧的图 1 PlantUML 源已归档到 `_archive/01-layers-plantuml-旧版.puml`。
- 归档：`_archive/`（需求分析 v2、设计方案 v3 模块视图、环境 v3），只供查阅，别当现行文档改。注意 `_archive/设计方案-v3.md` 用的是 M01–M13 旧编号，现行是 M1–M15，别混用。

## 层次与技术栈（现行）
L1 用户接入（Vue 3 + Element Plus、Django Admin）/ L2 接口服务（Nginx、Django ASGI、django-ninja）/ L3 编排调度 / L4 智能能力（Embedding、检索融合重排、提示工程、大模型 API）/ L5 知识资产（PG+pgvector、MinIO、解析流水线）/ L6 模型服务（httpx、供应商适配器、重试降级）/ L7 数据与基础设施（PG、Redis、MinIO、异步任务、容器）。

## 依赖规则（用户明确要求）
- **Python 定 3.10**（Django 5.2 最低支持版本），不用 3.11/3.12。
- **不确定是否使用的包不写进依赖文档**；开发中新装了依赖，**当次同步补进 `02-环境与依赖/环境需求与依赖.md`**，并在表内标"层"。
- 已剔除的候选（用到再加）：pydantic-settings、django-simple-history、simpleui、pdfplumber、python-docx、beautifulsoup4、lxml、numpy、structlog、prometheus-client、mypy、pre-commit、pytest-asyncio、vitest、eslint、prettier、pdfjs-dist、dayjs。

## 文档编辑口径（2026-10-24 校准后）
- 阶段文档只写"该阶段定下的、现在仍成立的设计与契约"，现在时，与代码逐条对过；代码变了先改文档再提交。
- **不写**实测记录、踩坑表、"当初怎样后来改成"、代码行数、测试用例数、调试故事。度量只在 `P7 §11.2` 与 `docs/04-评测/reports/`。
- 被后续阶段解决的临时态直接删除；同一事实只在归属阶段写一次，其余用 `§` 指针（缓存冷热 P2 定义、P7 讲报告口径）。
- 已知限制统一三列：限制 / 影响 / 处理方式；不处理的写"不做"，不写不会兑现的"何时处理"。
- 环境变量名、接口数量、tab 数这类计数最容易漂，改完 `grep` 一遍再收工。

## 写作风格
- 直接给结论/清单/表格/坑，不写"为什么、意义、价值"式论证；段落不超过三行。
- 表格优先于段落；PlantUML 而非 ASCII 图。
- **做不到就停下直说**，不要为了满足要求硬凑技巧方案（用户明确要求过）。

## 工程现状（P0、P1 已落地）
- P0 目录：`config/`（env、api、urls、asgi、settings/base+dev+prod）、`apps/common`（checks + health + storage）、`deploy/`（docker-compose.yml、docker-compose.minio-alt.yml、pg/init）、`web/`（Vite 6 + Vue 3.5 + TS + Element Plus）、`tests/`。
- P1 目录：`apps/knowledge/`（models 六表 documents/chunks/matters/flows/terms/ingest_jobs、repositories 读写分离、parsing/{base,pdf,text}、chunking、ingest、queue、api、admin、management/commands 四个、fixtures/terms.csv）。
- 常用命令：`uv run python manage.py ingest corpus/ --publish` → `worker --once`；`seed_terms`；`/api/kb/stats`、`/api/kb/jobs`。
- 启动：`docker compose --env-file .env -f deploy/docker-compose.yml up -d`（官方 MinIO 镜像拉不到时叠加 `-f deploy/docker-compose.minio-alt.yml`）→ `uv run uvicorn config.asgi:application --reload --port 8000` → `cd web && pnpm dev`。
- **compose 的 `--env-file` 不能省**：service 的 `env_file` 不参与 `${}` 插值，漏了会把 PG 口令洗成空串。healthcheck 用 `$$VAR` 交给容器内 shell。
- MinIO 官方镜像 2025 起下架（hub 无仓库、quay 匿名 401），本机用 `bitnamilegacy/minio:latest` 兜底。
- 本机有 `HTTP_PROXY`，探本机端口一律绕过：httpx 用 `trust_env=False`，curl 用 `--noproxy '*'`。
- 前端包管理用 pnpm 9（corepack 激活）；验证页面用 Chrome headless 截图。
- 语料 50 份在 `corpus/`（gitignore），生成脚本 `.workbuddy/tmp/gen_corpus.py`；验收统计脚本 `.workbuddy/tmp/verify_p1.py`。
- P2 已落地（`apps/gateway/`，G1–G9 全过）。口径：2 个适配器（openai_compat + rerank）、不装模型 SDK、embedding 不做运行期降级、熔断按槽位 main/fallback/aux/embed/rerank、新增依赖 0。
- **供应商现状（五槽位全通）**：`main`=DeepSeek deepseek-chat｜`fallback`=百炼 qwen-plus｜`aux`=百炼 qwen-flash｜`embed`=硅基 bge-m3（1024 维，116 块已回填）｜`rerank`=硅基 bge-reranker-v2-m3。main 与 fallback 跨厂。`GW_EMBED_*`/`GW_RERANK_*` 允许空。
- **百炼 key 前缀不能当可用性判据**：两个 `sk-ws-` 一个 401 过期、一个 200。拿到 key 先 `gw_probe`；Coding Plan 只通 `coding.dashscope.aliyuncs.com`，按量付费走 `compatible-mode`，跨地域 key 不通用。
- **`qwen-turbo` 已下架**：裸模型名不在百炼模型列表（178 个）里，调用回 `429 limit_requests`（看着像限流）。廉价档用 `qwen-flash`。429 家族要分：`limit_requests`/`insufficient_quota`=限流，`400 Arrearage`=欠费，`403 FreeTierOnly`=免费额度耗尽，`429 BudgetLimitExceeded`=预算到顶。

## 环境坑
- Obsidian 可能开着 docs 回写旧缓冲：写完必须 `wc -l -c` + `head -3` 复核，发现截断立即重写。
- 本机 Java 21 + `.workbuddy/tmp/plantuml.jar` 可渲染校验 PlantUML；PNG 文件名默认取 `@startuml` 后的图名，需手动改名。
- `re.subn` 的 replacement 会解析 `\n`，替换 PlantUML 源码要用 `lambda m: ...`。

## P3 智能能力（已落地）
- 包 `apps/qa/`，模块化：`understand`(M5) `retrieve`(M6) `matters`(M7) `generate`(M8) `verify`(M9)，入口 `pipeline.qa.answer/answer_stream`；提示模板在 `apps/qa/prompts/*.txt`，用 `string.Template` 的 `$var`，**不要改成 str.format**（证据里有花括号）。
- **门槛铁律**：可答判定只用绝对量（重排分 / 余弦 `QA_MIN_VECTOR_SIM=0.58` / 命中词数），不用 RRF 融合分——融合分只表达排名，全库带向量时恒为 1.0。
- **async 里不许直接查库**：词典改写、事项匹配都 `asyncio.to_thread`，否则 `SynchronousOnlyOperation`。
- 拒答四类 `out_of_scope / no_evidence / low_confidence / ungrounded`，文案是 `prompts.py` 常量，改文案只改一处；四类都要能触发样例。
- 清单三类 `material / step / condition`，**注意事项不进清单**（散文切出来全是碎片）；流程/材料只认有序号条目；只从与命中事项同标题的块里抽。
- 数值核对：中文数字（一–九十九）与阿拉伯互认，单位归一（块→元、个工作日→工作日），`一次性/一站式` 先排除。
- 命令：`manage.py seed_matters`（按 guide 语料生成 25 事项 / 78 步骤，幂等，P6 前基线）、`qa_ask`、`qa_eval --show-fail`（黄金集在 `apps/qa/fixtures/golden.jsonl`，39 条）。
- 评测数字会骗人：`QA_ANSWER_TEMPERATURE=0.2` 命中 P2 的 L1 缓存，第二遍跑是 40–80ms 的缓存延迟，报延迟必须说明冷/热。
- 已知限制写在 P3.md §14（长句多轮省略、冲突只覆盖费用与时限、中文数字只到 99、清单依赖序号、引用出处显示块首小节）。

## P4 会话与编排（已落地）
- 包 `apps/orchestrator/`（M4）：`session`(Redis 热态) `router`(direct/single/fanout) `capabilities`(超时兜底) `assembler`(多段装配) `events`(SSE) `orchestrator`(turn/stream) `api`。入口 `orc.turn()` / `orc.stream()`。
- 两张表：`conversations` / `messages`（同一 (会话,轮次,role) 唯一，payload 存整份 TurnResult）。Redis 键 `orc:sess:{cid}` 只放上下文窗口，**丢了从 messages 重建**。
- **trace_id 是 UUID 字段**：多段 fan-out 必须共用一个 uuid，不能拼 `:0` 后缀（否则台账落库 ValidationError）。
- **旁路设施异常不得穿过主链路**：`meter.flush_sync` / `add_spend` 已包 try/except，落库失败只丢这批。
- SSE 七事件 `session/stage/delta/answer/notice/error/done`，**done 恒收尾，出错也发**；POST + fetch 流式读（不用 EventSource）；心跳是注释行 `: ping`。
- 路由：≥2 个子问题才 fanout（≤`ORC_FANOUT_MAX`=3）；指代补全只对 ≤10 字问句，长句里的"这个/它"当新话题。
- 流式只有 single 是真流式，fanout 整段吐（并行无法边算边拼），且流式不做修复重写。
- Python 3.10：`asyncio.TimeoutError` ≠ 内置 `TimeoutError`，且 ruff UP041 会改写 → 用 `asyncio.exceptions.TimeoutError` 别名。
- 测试：`meter` 是进程级全局缓冲，conftest 已加 autouse `meter.reset()`；新用例别再手动清缓冲。

## P5 接入层 / P6 知识运营（已落地）
- `apps/access/`：中间件顺序 **TraceId → Audit → Access**（审计在外，401/429 也要留痕）；身份两枚演示 token `student-demo`/`admin-demo`，`/api/ops` 前缀要求 admin；限流三桶 chat20/write60/read120，Redis 挂了放行；对外 `/api/chat/*`，内部 `/api/orc/*`。
- `apps/ops/`：上传→暂存区 `var/uploads/{checksum12}/{原名}`→`ingest_jobs`→队列；**草稿入库不归档在版版本**（P1 `process_file` 已改：只有 publish=True 才 archive）；发布/回滚都走 `_publish`（archive_existing + publish + 清 `gw:kb:fingerprint` 与 `qa:terms`）。
- 模型槽位覆盖表 `model_settings` + `gateway/overrides.py`（30s 缓存，PUT 后 invalidate）；密钥只在 `.env`。
- 冲突检测 `apps/ops/conflict.py`：只比同事项（标题字符重合≥0.6）的费用/时限，费用要同时认 "X 元/份" 与 "每份 X 元"。
- 前端：三栏对话页（会话侧栏 / 消息流 / 原文+清单）、运营后台 5 tab；SSE 用 fetch 读流按 `\n\n` 切帧；`?token=` 换身份、`?c=<id>` 深链会话。
- **前端设计基线（2026-10-24 改版）**：暖纸 `#f4f1ea` + 墨 `#1b1a16` + 深绿 `#243b34`，宋体标题，无渐变/emoji；令牌在 `web/src/styles/main.css`，图标用 `AppIcon.vue`。桌面三栏，≤1180 依据抽屉、≤860 会话抽屉；流式消息必须用 `reactive` 对象，普通对象赋值不触发依据面板。运营页 `Admin.vue` 为 5 段导航 + KeepAlive。
- **后端结构**：`ops/schemas.py`（Ninja 模型）、`orchestrator/stats.py`（看板/评测共用统计）、`qa/pipeline._prepare`（生成前共用上下文）、`orchestrator._assemble/_empty_result`。`TurnResult` 顶层新增 `refusal_reason`（首段），前端类型已同步。
- 测试写法：`Client(SERVER_NAME="localhost")`；限流键清理用 `scan_iter("*acc:rl:*")`；上传测试用 `tmp_path` 覆盖 `OPS_UPLOAD_DIR`。

## P7 评测与反馈（已落地）
- 包 `apps/eval/`：`feedback`（候选池，含 expect=应可答/应拒答）、`eval_runs`（回归档案）；命令 `p7_eval` / `p7_drill` / `p7_golden`；只读接口 `/api/ops/{metrics,evals,feedback}`；学生端 `POST /api/chat/feedback`。
- **评测对象是 `qa.answer()`**（能力层），不是 `orc.turn`；跑批/演练只走命令行，HTTP 只读。
- **演练必须关 `GW_CACHE_ENABLED`**，否则命中 L1 缓存、故障不触发；失败口径 = 该拒答却作答 或 没答也没兜底，优雅降级不算错。
- 指标分母为 0 不判；报告 markdown 落 `EVAL_REPORT_DIR`（docs 被忽略）；延迟必须标冷/热（冷 3.5s vs 热 62ms）。
- 反馈不是黄金集：`p7_golden` 默认只打印，`--apply` 才追加并按问句去重、标记 reviewed。
- 实测基线（定稿 v4 冷 / v5 热）：39 条 hit@3/must/可答/拒答全 100%，引用 94%，冷 P50 3390ms / P95 4140ms / ¥0.2078，热 P50 62ms / ¥0。
- **演练报告已落盘**：`p7_drill` 复用 `runner.write_report`，产出 `docs/04-评测/reports/*-演练.md`（矩阵 + 逐场景判定 + 口径），`report_path` 写入 `eval_runs`。定稿演练五场景 5/5 通过，`main_timeout` degraded 5/5、P50 13.8s，`chat_all_down` 5/5 给原文出处。
- **`docs/` 已纳入版本控制**：`.gitignore` 只忽略 `.workbuddy/tmp/` 与 `docs/.obsidian/`；语料生成脚本在 `scripts/gen_corpus.py`（`corpus/` 仍忽略，克隆后先跑它）。
