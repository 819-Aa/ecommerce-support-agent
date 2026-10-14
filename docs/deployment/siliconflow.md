# DeepSeek-V4-Flash + BGE-M3 + BGE-Reranker-v2-M3 完整部署

本配置使用真实匿名 Olist 订单、MySQL 和真实在线模型，不运行离线 Mock 演示。

## 配置

复制 `.env.siliconflow.example` 为 `.env`，只在本机填写 `SILICONFLOW_API_KEY`。
不要将 `.env` 或密钥提交到 Git。接口地址为 `https://api.siliconflow.cn/v1`。

主模型由 `COMPATIBLE_MODEL` 选择，初始配置是 `deepseek-ai/DeepSeek-V4-Flash`；
请以账户模型列表和实际调用结果为准。`COMPATIBLE_API_KEY` 从同一份
`SILICONFLOW_API_KEY` 读取，不需要填写第二份密钥。

检索配置：

- `RAG_EMBEDDING_PROVIDER=siliconflow`：使用远程嵌入。
- `RAG_EMBEDDING_MODEL=BAAI/bge-m3`：为商城政策建立向量索引。
- `RAG_RERANK_ENABLED=true`：对混合召回候选进行远程重排。
- `RAG_RERANK_MODEL=BAAI/bge-reranker-v2-m3`：重排模型。
- `RAG_RELEVANCE_THRESHOLD=0.50`：初始向量相关度门槛，需要用评测验证。

订单、商品和支付数据通过 SQL 查询，不进行全量向量化。模拟商城政策仍是项目构造的
知识库；使用真实订单不代表政策也来自 Olist。

明确选择 `CUSTOMER_SUPPORT_MODE=compatible` 后，缺少主模型密钥会报错，
不会退回 Mock。嵌入和重排接口错误也会明确报错，不会静默使用本地模型。

## 准备订单数据

从 https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce 下载 CSV，
放到 `data/raw/olist/`，然后执行：

```powershell
uv sync --frozen --python 3.12
.\.venv\Scripts\python.exe scripts\import_olist.py --report data\raw\olist_import_report.local.json
```

得到 `data/olist_support.db` 后，Docker 的迁移容器会将它导入 MySQL。
SQLite 在此处是导入中间文件；运行时订单和工单走 MySQL，对话检查点仍用 SQLite。

## 启动和验收

启动 Docker Desktop 后执行：

```powershell
docker compose up --build -d
.\.venv\Scripts\python.exe scripts\verify_docker.py
.\.venv\Scripts\python.exe scripts\verify_qwen_docker.py
```

最后一个脚本保留了原来的文件名，但现在验收当前配置的在线模型，包括 DeepSeek。
在线验收会产生模型调用费用。

访问 http://127.0.0.1:8501，依次验证：

1. `查询订单 OL099422，手机号后四位 3623，并告诉我物流是否延迟`
2. `七天无理由退款需要满足什么条件？请标注政策来源`
3. `为订单 OL099422 创建物流异常工单，手机号后四位 3623，问题是物流一直没有更新`
4. 在显示确认提示后回复 `确认`，检查工单创建结果。

只读数据库页面为 http://127.0.0.1:8081。

## 检索实验

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_rag.py --report data\evaluation\rag_report_siliconflow.json
```

开启重排后会分别报告 lexical、dense、hybrid、hybrid_rerank 四组结果。
API 延迟包含网络和远程推理，不能与 README 中本地 BGE 的毫秒级延迟直接比较。
更换嵌入模型会重建 Chroma 索引；已有报告也需要重新生成。

自动化单元测试强制使用本地测试配置，不调用真实客服模型、嵌入或重排 API。

## 本次检索结果（2026-10-13）

使用仓库固定的 64 条相关问题和 8 条越界问题，BGE-M3 API 嵌入、BGE API 重排，
保持初始相关度门槛 0.50，结果如下：

| 方法 | Hit@1 | Hit@3 | 越界拒答率 | P95 检索延迟 |
| --- | ---: | ---: | ---: | ---: |
| lexical | 87.50% | 96.88% | 75.00% | 3.62 ms |
| dense | 90.62% | 98.44% | 87.50% | 109.18 ms |
| hybrid | 92.19% | 100.00% | 87.50% | 135.86 ms |
| hybrid_rerank | 96.88% | 100.00% | 87.50% | 325.49 ms |

结果文件是 `data/evaluation/rag_report_siliconflow.json`。重排提高了当前评测集的
第一命中率，但增加了检索延迟。两条相关问题第一命中仍有误，一个越界问题未被拒答。
这些结果来自本机检索实验，不代表线上业务准确率，也不包括主模型生成回答的时间。

## 当前启动与验收状态（2026-10-13）

- Olist 原始 CSV 已准备，生成了 91.5 MB 的 SQLite 导入快照。
- MySQL 迁移已成功，订单 99,441 条、商品明细 112,650 条。
- MySQL、FastAPI、Streamlit、只读数据库浏览器均已通过 Docker 健康检查。
- `verify_docker.py`：5/5 项通过。
- 全量单元测试：175 项通过、2 项原有模拟 Docker 集成测试跳过；变更文件 Ruff 通过。
- DeepSeek 独立工具调用、嵌入和重排 API 均已成功调用。
- 充值后，真实在线订单查询和政策检索验收通过；工单确认、重复申请幂等、取消零写入、
  缺少拆封数据时转人工审核、SSE 流式回复均已验证。
- 在线验收报告：`data/evaluation/online_acceptance_siliconflow.json`，12/12 项通过。
- 验收工单 `OTK-5F12B317` 保留在 MySQL，分类为“联调验收”，可在数据库浏览器中查看。

当前服务保持运行，可直接访问客服网页和数据库浏览器，无需重新导入订单。
本次验收还修复了取消工单后模型再次询问确认的问题，见
`docs/learning/bug-004-hitl-cancellation.md`。

官方接口参考：

- https://docs.siliconflow.cn/docs/api/chat-completions-post
- https://docs.siliconflow.cn/docs/api/embeddings-post
- https://docs.siliconflow.cn/docs/api/rerank-post

日常停止使用 `docker compose down`，保留数据卷。
