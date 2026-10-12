# Backend Embedding 配置

在 `backend/.env` 中配置 `DEEPSEEK_API_KEY=你的 DeepSeek 密钥` 和 `SILICONFLOW_API_KEY=你的硅基流动密钥`，并从 `backend` 目录启动服务。问答使用 DeepSeek 的 `deepseek-chat`；相关性判断使用硅基流动的 `Qwen/Qwen3.8-27B`；建索引、直接搜索和 RAG 检索使用硅基流动的 `Qwen/Qwen3-Embedding-8B`。可通过 `SILICONFLOW_GRADER_MODEL`、`SILICONFLOW_EMBEDDING_MODEL` 和 `SILICONFLOW_BASE_URL` 覆盖硅基流动的模型与地址；Embedding 模型必须支持 Embedding 接口。

`Qwen/Qwen3.8-27B` 是对话模型，不能用于 Embedding。切换 Embedding 模型后，需调用 `/api/v1/index/build` 为文档重新构建 FAISS 索引；旧索引会返回 `INDEX_REBUILD_REQUIRED`。

## PDF 解析

有可提取文字的 PDF 会直接读取文字层，并定位页面上实际显示的图片；解析页会分别标记文本和图片区域，同时导出图片文件与 Markdown，不需要 Tesseract 或下载布局模型。扫描版 PDF 仍使用 Unstructured OCR；运行扫描件解析前，需要在系统中安装 Tesseract OCR 及对应语言包。`/api/v1/pdf/status` 的 `errorMsg` 会返回具体失败原因。

## 启动服务

```bash
cd backend
uvicorn app:app --reload --port 8001
```
