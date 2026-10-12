import { HealthCheck } from './HealthCheck';

export function Header() {
  return (
    <header className="px-6 py-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-wide bg-gradient-to-r from-blue-400 via-purple-400 to-cyan-400 bg-clip-text text-transparent">
            多模态 RAG 检索系统
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">上传 PDF，检索内容并与文档对话</p>
        </div>
        <HealthCheck />
      </div>
    </header>
  );
}
