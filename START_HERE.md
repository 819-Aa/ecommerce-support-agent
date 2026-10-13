# 从这里开始：电商智能客服与 RAG 知识库

你现在不需要懂 LangGraph、FastAPI、数据库或 Docker。第一阶段的目标只有一个：

> 在浏览器中完成“查政策 → 查订单 → 判断退款 → 确认创建工单”。

## 第一次使用

在项目目录空白处按住 `Shift` 并点击鼠标右键，选择“在此处打开 PowerShell”，运行：

```powershell
.\scripts\setup_demo.cmd
```

第一次会下载约 90MB 的中文 Embedding 模型。看到 RAG 的三组指标且客服模块测试
全部通过，表示环境、知识库、模拟数据库和核心业务代码都正常。

## 启动

```powershell
.\scripts\start_demo.cmd
```

浏览器会打开 <http://127.0.0.1:8501>。

推荐依次输入：

```text
七天无理由退款有什么要求？
快递卡住好多天了，一直没有更新怎么办？
公司要报销，订单完成后二十天能补票吗？
查询订单 ORD1001，手机号后四位 8821
订单 ORD1002 能退款吗？手机号后四位 8821
订单 ORD1003 能退款吗？手机号后四位 8821
为 ORD1001 创建人工客服工单，手机号后四位 8821
确认
```

模拟数据只有一位用户，手机号后四位固定为 `8821`：

| 订单 | 状态 | 用途 |
| --- | --- | --- |
| `ORD1001` | 运输中 | 测物流和订单查询 |
| `ORD1002` | 签收 3 天、未拆封 | 测可以退款 |
| `ORD1003` | 签收 12 天、已拆封 | 测拒绝退款 |

## 自动验收

保持项目正在运行，然后另开一个 PowerShell：

```powershell
.\scripts\run_tests.cmd
```

看到 `验收结果：9/9 项通过` 表示当前业务主流程和 RAG 路由都正常。

## 单独做 RAG 实验

```powershell
.\scripts\evaluate_rag.cmd
```

你会看到三种检索方法的对比：

- `lexical`：只比较文字是否重合，速度快，但不理解同义表达；
- `dense`：用中文 Embedding 理解语义，再从 Chroma 找相近切片；
- `hybrid`：把两路结果按排名和重合强度融合。

评测集包含 64 条相关问题和 8 条越界问题。`Hit@1` 表示第一条结果答对的比例，
`Hit@3` 表示前三条中包含正确政策的比例；同时报告 MRR@3、越界拒答率和 P95 检索
延迟。逐题错误保存在 `data/evaluation/rag_report.json`。

单独运行 Agent 业务验收：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_agent.py
```

它验证确定性路由、退款规则、身份校验和工单幂等，详细结果写入
`data/evaluation/agent_report.json`。

## 切换到真实 Qwen Agent

默认 `.env.mock.example` 使用离线规则 Agent，不产生模型费用。真实 Qwen 模式需要在
本地 `.env` 中配置：

```env
CUSTOMER_SUPPORT_MODE=auto
DASHSCOPE_API_KEY=只保存在本机的Key
DASHSCOPE_BASE_URL=https://你的业务空间.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=qwen3.7-plus-2026-05-26
```

可参考 `.env.qwen.example`，但绝不能把真实 Key 写进示例文件、代码或 Git。

连接与工具调用测试：

```powershell
.\.venv\Scripts\python.exe scripts\check_qwen_connection.py
.\.venv\Scripts\python.exe scripts\check_qwen_tool_call.py
```

真实客服 Agent 会调用政策、订单、退款资格和工单工具。创建工单属于写操作，程序会
硬性暂停，只有用户回复“确认”后才执行。

在线模式下，`run_tests.cmd`会自动跳过9条HTTP批量用例，避免意外产生多次API费用。
请在网页中手动验收订单查询、RAG政策问答和工单确认三条必要链路。

## 停止

```powershell
.\scripts\stop_demo.cmd
```

## Docker + MySQL 完整部署

本地学习版使用 SQLite；完整部署版会把 99,441 条 Olist 订单迁入 MySQL，并用
Docker Compose 同时运行 MySQL、FastAPI Agent 和 Streamlit。

Docker Desktop 安装并启动后，运行：

```powershell
.\scripts\start_docker.cmd
.\scripts\verify_docker.cmd
.\scripts\verify_qwen_docker.cmd
```

详细的启动、验收、日志排查和面试讲法见：
[Docker + MySQL 部署说明](docs/deployment/docker-mysql.md)。

图形化查看 MySQL：打开只读页面 <http://127.0.0.1:8081>，选择数据表即可查看，
无需输入数据库命令或密码。

## 报错怎么办

不要乱删文件，也不用重装电脑。把 PowerShell 的红字发给 Codex，我会根据日志继续排查。

运行日志位于：

```text
data/logs/service.err.log
data/logs/app.err.log
```

## 学习与问题记录

- [Bug 001：发票政策问题被错误路由到订单查询](docs/learning/bug-001-order-policy-routing.md)
- [Bug 002：Qwen Agent 接入后的事件处理错误](docs/learning/bug-002-qwen-agent-event-handling.md)
- [Bug 003：PowerShell 中文请求被编码成问号](docs/learning/bug-003-powershell-utf8-e2e.md)
- [Olist匿名真实电商数据说明](docs/data/olist-dataset.md)

## 这一阶段你已经学到了什么

- Git 仓库是项目代码的版本历史。
- uv 为项目建立独立 Python 环境并安装依赖。
- FastAPI 提供 HTTP 接口。
- LangGraph 保存对话状态，使“确认”能接着上一句话执行。
- SQLite 保存模拟订单和工单。
- Markdown 政策按标题解析并切成可检索片段。
- BGE 中文 Embedding 把问题和政策转换为 512 维向量。
- Chroma 将向量持久化到本地，避免每次启动重复建库。
- 混合检索融合语义召回与字符召回，并返回文件和章节引用。
- 小型评测集用 `Hit@1`、`Hit@3` 和平均延迟衡量效果。
- pytest 用固定输入验证固定输出，避免人工猜测程序是否正确。
