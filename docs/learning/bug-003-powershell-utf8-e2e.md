# Bug 003：PowerShell 管道让中文验收请求变成问号

## 现象

Docker 中的 Qwen Agent 对“七天无理由退款需要满足什么条件”返回功能菜单，没有调用
`search_policy`。连续修改 Prompt 后现象仍存在。

## 定位

为 Agent 中间件增加不记录原文的消息类型和长度日志，确认收到 `HumanMessage`；
临时对固定测试文本记录一次 `repr`，发现内容是 23 个 `?`。原因是 Windows
PowerShell 将 here-string 通过管道传给 Python 时发生编码转换，中文在发出 HTTP
请求前已经丢失。

## 修复

- 新增 `scripts/verify_qwen_docker.py`，以 UTF-8 源文件保存中文测试用例。
- `json.dumps(..., ensure_ascii=False).encode("utf-8")`。
- 请求头明确设置 `Content-Type: application/json; charset=utf-8`。
- 删除临时原文日志，避免记录用户消息。

## 验证

正式脚本输出：

- `Qwen → Function Calling → MySQL`：通过。
- `Qwen → 强制政策路由 → BGE/Chroma RAG`：通过。

## 经验

当模型行为异常时，先检查进入模型前的原始输入、编码和消息结构。界面上看起来像
Prompt 或 Function Calling 问题，根因也可能在测试客户端。
