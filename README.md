# 多模态 RAG 检索系统

基于 React、FastAPI、MinerU、FAISS 和 LangChain 的 PDF 问答项目。上传 PDF 后，系统解析文字、表格、公式和图片，建立统一的图文向量索引，再结合文档引用生成回答。

## 处理流程

1. **解析 PDF**：后端使用 `mineru-open-sdk==0.2.5` 的精细解析模式（`model="vlm"`），启用 OCR、公式和表格识别。MinerU 返回的原始 Markdown 保存在 `output.md`，图片保存在 `images/`，`content_list.json` 用于定位页码和绘制解析区域。PyMuPDF 只负责页数统计与页面预览；不再使用本地 Tesseract 转 Markdown。
2. **建立索引**：按 MinerU 内容列表的页码组织文字；图片先由硅基流动的视觉模型生成中文描述。文字与图片像素使用同一个视觉语言 Embedding 模型编码，写入 FAISS 索引。图片较多时，索引阶段会逐张调用外部模型，耗时可能较长。
3. **召回与回答**：聊天默认从统一索引中取距离最近的 5 个图文片段。FAISS 对向量做 L2 归一化，使用平方欧氏距离排序，距离越小越相近。随后 Qwen 对整组片段做一次 `yes/no` 相关性判断；当前没有逐条重排或相似度阈值。相关时，DeepSeek 使用片段和页码引用生成流式回答；否则明确说明未找到匹配的文档片段。

## 所需环境

- Python 3.10 或更高版本、Node.js 和 npm。
- `MINERU_TOKEN`：MinerU 精细解析。上传的 PDF 会发送到 MinerU API。
- `SILICONFLOW_API_KEY`：图片描述、图文 Embedding 和相关性判断。
- `DEEPSEEK_API_KEY`：问答生成。

配置示例见 [backend/.env.example](backend/.env.example)。密钥写入 `backend/.env`，该文件已被 Git 忽略。可用 `SILICONFLOW_VISION_MODEL`、`SILICONFLOW_EMBEDDING_MODEL`、`SILICONFLOW_GRADER_MODEL` 和 `SILICONFLOW_BASE_URL` 覆盖默认模型与服务地址。

## 启动

首次安装依赖：

```bash
cd backend
python -m pip install -r requirements.txt
cd ../frontend
npm ci
cd ..
```

在 `backend/.env` 配好三个服务凭据后，从项目根目录运行：

```bash
./restart.sh
```

前端地址为 `http://127.0.0.1:3000`，后端为 `http://127.0.0.1:8001`，API 文档位于 `http://127.0.0.1:8001/docs`。脚本支持 `start`、`stop`、`restart`、`status`，日志写入 `.run/`。如需指定解释器，设置 `BACKEND_PYTHON=/path/to/python`。手动启动方式见[后端说明](backend/README.md)和[前端说明](frontend/README.md)。

## 数据与验证

每次上传的原始 PDF、MinerU 输出、页面预览和 FAISS 索引保存在 `backend/data/<fileId>/`，该目录已被 Git 忽略。已解析的旧文件不会自动改用 MinerU，需重新上传并建立索引。

```bash
cd backend
python -m unittest discover -s tests -v
cd ../frontend
npm run build
```
