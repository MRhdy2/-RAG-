# 多模态 RAG 检索系统

一个基于 React、FastAPI 和 LangChain 的 PDF 智能问答项目。系统支持 PDF 上传、文字与 OCR 解析、图片区域标注和页面预览；使用硅基流动 Qwen Embedding 与 FAISS 检索文档，由 Qwen 判断内容相关性，再通过 DeepSeek 流式生成带文档引用的回答。

## 功能

- 上传 PDF，查看原始页面和标注了文本、图片区域的解析页面。
- 提取文字及嵌入图片，生成 Markdown 并建立 FAISS 向量索引。
- 根据文档片段回答问题，显示引用片段和对应页面。
- PDF 有文字层时直接提取；扫描版 PDF 使用 Unstructured OCR，需在系统中安装 Tesseract 及对应语言包。

## 启动

1. 安装后端依赖，并在 `backend/.env` 中配置密钥。可复制 `backend/.env.example` 作为模板：

   ```bash
   cd backend
   pip install -r requirements.txt
   cp .env.example .env
   # 编辑 .env，填入自己的 DEEPSEEK_API_KEY 和 SILICONFLOW_API_KEY
   uvicorn app:app --reload --port 8001
   ```

2. 在另一个终端启动前端：

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

3. 打开 `http://localhost:3000`。如需修改后端地址，可参照 `frontend/.env.local.example` 设置 `frontend/.env.local`。

## 处理流程

`PDF 上传 → 页面解析与 Markdown → Qwen Embedding → FAISS 检索 → Qwen 相关性判断 → DeepSeek 回答`

目前图片会被定位、提取和标注；向量索引主要基于提取的文字，尚未对图片像素内容建立视觉向量索引。运行时上传文件和索引保存在 `backend/data/`，该目录及本地密钥文件均已加入 `.gitignore`。
