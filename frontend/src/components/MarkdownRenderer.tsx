import React, { useMemo, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import { defaultSchema } from "hast-util-sanitize"; // ⭐ 新增
import { FileText, ExternalLink } from "lucide-react";
import { toAbsoluteApiUrl } from "../services/api";
// ⭐ 允许 <img> 的自定义 schema（在组件外或组件内 useMemo 都可）
const sanitizeSchema = {
  ...defaultSchema,
  tagNames: [...(defaultSchema.tagNames || []), "img"],
  attributes: {
    ...(defaultSchema.attributes || {}),
    "*": [...((defaultSchema.attributes && defaultSchema.attributes["*"]) || []), "className"],
    img: [
      "src",
      "alt",
      "title",
      "loading",
      "width",
      "height",
      "className",
    ],
    a: [
      ...((defaultSchema.attributes && defaultSchema.attributes["a"]) || []),
      "target",
      "rel",
    ],
  },
  protocols: {
    ...(defaultSchema.protocols || {}),
    src: ["http", "https", "data", "blob"],
    href: ["http", "https", "mailto", "tel"],
  },
};

/** 代码块（带复制） */
function Code(props: any) {
  const { inline, className, children } = props;
  const language = (className || "").replace("language-", "") || "code";
  if (inline) {
    return <code className="bg-muted/50 px-1.5 py-0.5 rounded text-sm">{children}</code>;
  }
  return (
    <div className="my-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-muted-foreground">{language}</span>
        <button
          className="text-xs px-2 py-1 rounded bg-white/10 hover:bg-white/20"
          onClick={() => navigator.clipboard.writeText(String(children))}
        >
          Copy
        </button>
      </div>
      <pre className="text-sm overflow-x-auto bg-slate-900/80 p-3 rounded border border-slate-700/50">
        <code className="text-slate-200">{children}</code>
      </pre>
    </div>
  );
}

/** 图片：忽略本地相对路径，只渲染可访问的 API/HTTP 图片 */
function Img(props: React.ImgHTMLAttributes<HTMLImageElement>) {
  const fixedSrc = useMemo(() => {
    const src = String(props.src || "");
    if (!src) return "";

    // 忽略 md 中的本地相对图片（前端访问不到）
    if (src.startsWith("./images/") || src.startsWith("images/")) return "";

    // /api/... 或绝对地址
    return toAbsoluteApiUrl(src);
  }, [props.src]);

  const [err, setErr] = useState(false);
  useEffect(() => setErr(false), [fixedSrc]);
  if (!fixedSrc || err) return null;

  return (
    <img
      {...props}
      src={fixedSrc}
      onError={() => setErr(true)}
      className={"max-w-full h-auto rounded-lg border border-border/30 shadow-sm " + (props.className ?? "")}
      loading="lazy"
    />
  );
}

/** 引用内容直接来自聊天流中的 citation 事件。 */
function ReferenceCard({ reference, index }: { reference: Reference; index: number }) {
  const snippet = reference.snippet || "";
  const previewUrl = reference.previewUrl ? toAbsoluteApiUrl(reference.previewUrl) : "";
  const imageUrl = reference.imageUrl ? toAbsoluteApiUrl(reference.imageUrl) : "";

  return (
    <div className="bg-muted/20 rounded-lg p-3 border border-border/30">
      <div className="flex items-start gap-3">
        <span className="inline-flex items-center justify-center w-6 h-6 text-xs font-medium bg-primary/20 text-primary rounded-full shrink-0">
          {index + 1}
        </span>
        <div className="flex-1 min-w-0">
          <div className="text-sm text-foreground leading-relaxed whitespace-pre-wrap">
            {snippet ? (snippet.length > 200 ? snippet.slice(0, 200) + "…" : snippet) : "（无文本片段）"}
          </div>
          {reference.kind === "image" && imageUrl && (
            <img src={imageUrl} alt={`第 ${reference.page ?? "?"} 页检索图片`} className="mt-2 max-h-48 max-w-full rounded border border-border/30 object-contain" loading="lazy" />
          )}
          {previewUrl && (
            <a
              className="mt-2 inline-flex items-center text-xs px-2 py-1 rounded bg-white/10 hover:bg-white/20"
              href={previewUrl}
              target="_blank"
              rel="noopener noreferrer"
            >
              <ExternalLink className="w-3 h-3 mr-1" />
              {reference.kind === "image" ? "查看图片" : "查看原页"}
            </a>
          )}
        </div>
      </div>
    </div>
  );
}

export type Reference = {
  id: number;
  text?: string;
  page?: number;
  citationId?: string;
  rank?: number;
  snippet?: string;
  previewUrl?: string;
  kind?: "text" | "image";
  imageUrl?: string;
};

export function MarkdownRenderer({
  content,
  references = [],
}: {
  content: string;
  references?: Reference[];
}) {
  // 在进入渲染前，移除碎片 <img ...> 与相对图片的 MD 标记，避免出现“图片不可用”占位
  const sanitizedContent = useMemo(
    () =>
      content
        .replace(/<img[\s\S]*?>/gi, "") // 去掉碎片 HTML img
        .replace(/!\[[^\]]*]\(\s*(?:\.\/)?images\/[^)]+\)/gi, ""), // 去掉相对路径 MD 图片
    [content]
  );

  return (
    <div className="space-y-3 text-foreground leading-relaxed prose prose-invert max-w-none">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw, [rehypeSanitize, sanitizeSchema]]}
        components={{
          img: Img,
          code: Code,
          table: (p) => <table {...p} className="w-full border-collapse border border-border/30 rounded-lg overflow-hidden" />,
          thead: (p) => <thead {...p} className="bg-muted/30" />,
          th: (p) => <th {...p} className="px-3 py-2 border border-border/30 text-left font-medium" />,
          td: (p) => <td {...p} className="px-3 py-2 border border-border/30 text-sm" />,
          h1: (p) => <h1 {...p} className="text-2xl font-medium mt-4 mb-3" />,
          h2: (p) => <h2 {...p} className="text-xl font-medium mt-4 mb-2" />,
          h3: (p) => <h3 {...p} className="text-lg font-medium mt-3 mb-2" />,
          ul:  (p) => <ul {...p} className="list-disc pl-5 space-y-1" />,
          ol:  (p) => <ol {...p} className="list-decimal pl-5 space-y-1" />,
          a:   (p) => <a {...p} className="text-primary underline underline-offset-4" target="_blank" />,
        }}
      >
        {sanitizedContent}
      </ReactMarkdown>

      {/* 相关文档片段（只展示 snippet + 查看原页），不再渲整页大图 */}
      {references?.length > 0 && (
        <div className="mt-4 pt-4 border-t border-border/30">
          <div className="flex items-center gap-2 mb-2">
            <FileText className="w-4 h-4 text-primary" />
            <span className="text-sm font-medium">相关文档片段</span>
            <span className="text-xs text-muted-foreground">({references.length})</span>
          </div>
          <div className="space-y-2">
            {references.map((r, i) => (
              <ReferenceCard key={r.citationId || i} reference={r} index={i} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
