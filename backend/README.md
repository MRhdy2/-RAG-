# 后端说明

FastAPI 服务提供 PDF 上传与解析、图文索引、检索和流式问答。默认地址为 `http://127.0.0.1:8001/api/v1`。

## 配置与启动

建议使用 Python 3.10 或更高版本。安装依赖后，在 `backend/.env` 中设置：

| 变量 | 用途 |
| --- | --- |
| `MINERU_TOKEN` | MinerU 精细解析 PDF；解析时文件会上传到 MinerU |
| `SILICONFLOW_API_KEY` | 图片描述、图文 Embedding、相关性判断 |
| `DEEPSEEK_API_KEY` | `deepseek-chat` 流式回答 |

参考 [.env.example](.env.example)。可选的 `SILICONFLOW_VISION_MODEL`、`SILICONFLOW_EMBEDDING_MODEL`、`SILICONFLOW_GRADER_MODEL` 和 `SILICONFLOW_BASE_URL` 用于覆盖默认配置。勿将真实密钥提交到仓库。

```bash
cd backend
python -m pip install -r requirements.txt
uvicorn app:app --reload --port 8001
```

也可以从项目根目录运行 `./restart.sh` 同时启动前后端。

## PDF 解析

`/pdf/upload` 保存原文件，`/pdf/parse` 启动后台解析，前端通过 `/pdf/status` 查询 `idle`、`parsing`、`ready` 或 `error`。解析失败时，状态响应包含 `errorMsg`。

解析使用 `mineru-open-sdk==0.2.5` 的 `MinerU.extract(model="vlm", ocr=True, formula=True, table=True, language="ch")`。MinerU 的 Markdown 原样写入 `data/<fileId>/output.md`；图片写入 `images/`；`content_list.json` 保留文本、表格、图片及其页码；`image_pages.json` 保存图片与页码的对应关系。PyMuPDF 只用于统计页数、渲染原始页面及绘制 MinerU 返回的区域框，不参与 Markdown 转换。本地无需 Tesseract。

每个文件的运行时数据都位于 `data/<fileId>/`，并已被 Git 忽略。

## 建立索引与召回

`/index/build` 读取 MinerU 内容列表，按 `page_idx` 建立有页码的文本块。图片由默认视觉模型 `Qwen/Qwen3.6-35B-A3B` 生成描述，描述按图片哈希和模型缓存在 `image_descriptions.json`；每次建索引仍需取得图片向量。文本和图片像素分别由默认的 `Qwen/Qwen3-VL-Embedding-8B` 编码，写入同一个 `index_faiss`。接口返回文本块数 `chunks` 和图片数 `images`。图片较多时，建索引会逐张请求外部模型，接口需等待整次构建完成。

聊天通过归一化向量的 FAISS 平方欧氏距离召回前 5 个结果，距离越小越接近。默认的 `Qwen/Qwen3.8-27B` 对**整组**结果做一次 `yes/no` 相关性判断，然后由 `deepseek-chat` 生成答案。当前没有逐条重排、相似度阈值或按文本/图片分别配额。独立的 `/index/search` 接口直接返回 FAISS Top K，不经过相关性判断。

若 Embedding 模型或索引格式变更，旧索引会返回 `INDEX_REBUILD_REQUIRED`，需重新调用 `/index/build`。

## 验证

```bash
cd backend
python -m unittest discover -s tests -v
```
