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

上传 PDF 后，前端会等待解析完成并建立索引，再启用文档问答。后端不可用时会显示实际错误，不会生成模拟回答或模拟文档。

运行 `npm run build` 生成生产文件，输出在 `build/`。
