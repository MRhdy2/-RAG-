# Backend Embedding 配置

在 `backend/.env` 中配置 `DEEPSEEK_API_KEY=你的 DeepSeek 密钥` 和 `SILICONFLOW_API_KEY=你的硅基流动密钥`，并从 `backend` 目录启动服务。问答使用 DeepSeek 的 `deepseek-chat`；相关性判断使用硅基流动的 `Qwen/Qwen3.8-27B`。PDF 文字段落和图片均使用 `Qwen/Qwen3-VL-Embedding-8B` 生成向量，写入同一个 `index_faiss` 索引；用户查询也由该模型编码后检索。图片仍由 `Qwen/Qwen3.6-35B-A3B` 生成内容描述，描述与图片向量关联并供问答使用。可通过 `SILICONFLOW_GRADER_MODEL`、`SILICONFLOW_EMBEDDING_MODEL`、`SILICONFLOW_VISION_MODEL` 和 `SILICONFLOW_BASE_URL` 覆盖模型与地址。

旧版分离的文本和图片索引不能用于统一检索，需调用 `/api/v1/index/build` 重建；旧索引会返回 `INDEX_REBUILD_REQUIRED`。索引构建会调用视觉模型处理每张导出的图片；描述保存在 `data/<fileId>/image_descriptions.json`，重复构建时会复用未变化图片的描述。`/api/v1/index/build` 返回文本块数 `chunks` 和图片数 `images`；`/api/v1/index/search` 的 `results` 字段按相似度统一返回文字和图片，使用 `kind` 区分。

## PDF 解析

PDF 会逐页读取文字层，并定位实际显示的图片。只有文字层不足且包含图片的页面会使用 PyMuPDF/Tesseract OCR；其余页面无需 OCR。解析结果保留页码，输出带文字、图片标注的页面图和 Markdown。

macOS 处理扫描页前请运行 `brew install tesseract tesseract-lang`，并用 `tesseract --list-langs` 确认包含 `chi_sim` 与 `eng`。其他系统需安装 Tesseract 及这两个语言包，必要时将 `TESSDATA_PREFIX` 指向存放 `.traineddata` 的目录。`/api/v1/pdf/status` 的 `errorMsg` 会返回具体失败原因。

## 启动服务

```bash
cd backend
uvicorn app:app --reload --port 8001
```
