const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8001/api/v1').replace(/\/$/, '');

export interface PdfUploadResponse {
  fileId: string;
  name: string;
  pages: number;
}

export interface ParseStatusResponse {
  status: 'idle' | 'parsing' | 'ready' | 'error';
  progress: number;
  errorMsg?: string;
}

export interface ChatCitation {
  citation_id: string;
  fileId: string;
  rank: number;
  page: number | null;
  previewUrl: string;
  snippet?: string;
}

export function toAbsoluteApiUrl(url: string): string {
  if (!url || /^(?:https?:|data:|blob:)/i.test(url)) return url;
  const base = new URL(API_BASE_URL, window.location.origin);
  return new URL(url, base.origin).href;
}

async function responseError(response: Response, label: string): Promise<Error> {
  const payload = await response.json().catch(() => null);
  const detail = payload?.error?.message || payload?.detail || response.statusText || response.status;
  return new Error(`${label}: ${detail}`);
}

export async function checkHealth(): Promise<{ ok: boolean; version: string }> {
  const response = await fetch(`${API_BASE_URL}/health`);
  if (!response.ok) throw await responseError(response, '健康检查失败');
  return response.json();
}

export async function uploadPdf(file: File): Promise<PdfUploadResponse> {
  const formData = new FormData();
  formData.append('file', file);
  const response = await fetch(`${API_BASE_URL}/pdf/upload`, { method: 'POST', body: formData });
  if (!response.ok) throw await responseError(response, '上传失败');
  return response.json();
}

export async function startParse(fileId: string): Promise<{ jobId: string }> {
  const response = await fetch(`${API_BASE_URL}/pdf/parse`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fileId }),
  });
  if (!response.ok) throw await responseError(response, '解析启动失败');
  return response.json();
}

export async function getParseStatus(fileId: string): Promise<ParseStatusResponse> {
  const response = await fetch(`${API_BASE_URL}/pdf/status?fileId=${encodeURIComponent(fileId)}`);
  if (!response.ok) throw await responseError(response, '解析状态获取失败');
  return response.json();
}

export function getPdfPageUrl(fileId: string, page: number, type: 'original' | 'parsed'): string {
  return `${API_BASE_URL}/pdf/page?fileId=${encodeURIComponent(fileId)}&page=${page}&type=${type}`;
}

export async function buildIndex(fileId: string): Promise<{ ok: boolean; chunks: number }> {
  const response = await fetch(`${API_BASE_URL}/index/build`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fileId }),
  });
  if (!response.ok) throw await responseError(response, '索引构建失败');
  return response.json();
}

export async function processChatStream(
  message: string,
  onToken: (text: string) => void,
  onCitation: (citation: ChatCitation) => void,
  onDone: (data: { used_retrieval: boolean }) => void,
  onError: (error: string) => void,
  pdfFileId?: string,
  sessionId = 'default',
  signal?: AbortSignal,
): Promise<void> {
  try {
    const response = await fetch(`${API_BASE_URL}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ message, sessionId, ...(pdfFileId && { pdfFileId }) }),
      signal,
    });
    if (!response.ok) throw await responseError(response, '聊天请求失败');
    if (!response.body) throw new Error('后端未返回聊天数据');

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let completed = false;

    const dispatch = (block: string): boolean => {
      const lines = block.split('\n');
      const eventType = lines.find((line) => line.startsWith('event:'))?.slice(6).trim();
      const eventData = lines.filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trimStart()).join('\n');
      if (!eventType || !eventData) return false;
      const data = JSON.parse(eventData);
      switch (eventType) {
        case 'token':
          onToken(data.text ?? '');
          break;
        case 'citation':
          onCitation(data as ChatCitation);
          break;
        case 'done':
          completed = true;
          onDone(data);
          return true;
        case 'error':
          completed = true;
          onError(data.message || '后端处理失败');
          return true;
      }
      return false;
    };

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer = (buffer + decoder.decode(value, { stream: true })).replace(/\r\n/g, '\n');
        const blocks = buffer.split('\n\n');
        buffer = blocks.pop() || '';
        for (const block of blocks) {
          if (dispatch(block)) return;
        }
      }
      buffer += decoder.decode();
      if (buffer.trim()) dispatch(buffer);
      if (!completed && !signal?.aborted) throw new Error('聊天连接提前结束');
    } finally {
      reader.releaseLock();
    }
  } catch (error) {
    if (signal?.aborted || (error instanceof DOMException && error.name === 'AbortError')) return;
    onError(error instanceof Error ? error.message : '未知错误');
  }
}

export async function clearSession(sessionId = 'default'): Promise<{
  ok: boolean;
  sessionId: string;
  cleared: boolean;
}> {
  const response = await fetch(`${API_BASE_URL}/chat/clear`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sessionId }),
  });
  if (!response.ok) throw await responseError(response, '清空会话失败');
  return response.json();
}
