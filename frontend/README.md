# 多模态 RAG 检索系统前端

从本目录安装依赖：

```bash
cd frontend
npm install
```

默认前端地址为 `http://localhost:3000`，后端地址为 `http://localhost:8001/api/v1`。如需修改后端地址，在本目录的 `.env.local` 中设置 `VITE_API_BASE_URL`。

# 前端启动

```bash
cd frontend
npm run dev
```

上传 PDF 后，前端先轮询 MinerU 解析状态，再调用后端建立图文索引。索引完成后才启用文档问答。图片会逐张处理，页面在整个索引请求结束前显示“正在建立检索索引…”，目前没有逐图进度；失败时会显示后端返回的错误。后端不可用时不会生成模拟回答或模拟文档。

运行 `npm run build` 生成生产文件，输出在 `build/`。
