import { useState, useRef, useEffect } from "react";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs";
import { Progress } from "./ui/progress";
import {
  Upload,
  FileText,
  ChevronLeft,
  ChevronRight,
  AlertCircle,
  CheckCircle2,
  Loader2,
  RefreshCw,
  File
} from "lucide-react";
import { uploadPdf, startParse, getParseStatus, buildIndex, getPdfPageUrl } from "../services/api";
import { toast } from "sonner";

type UploadStatus = 'idle' | 'uploading' | 'parsing' | 'indexing' | 'ready' | 'error';

interface PDFPanelProps {
  className?: string;
  onFileReady?: (fileId: string, fileName: string, totalPages: number) => void;
  onFileReset?: () => void;
}

function PagePreview({ fileId, page, type }: { fileId: string; page: number; type: 'original' | 'parsed' }) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return <p className="text-sm text-muted-foreground">第 {page} 页预览暂不可用</p>;
  }
  return (
    <img
      src={getPdfPageUrl(fileId, page, type)}
      alt={`${type === 'original' ? '原始' : '解析后'} PDF 第 ${page} 页`}
      className="max-w-full max-h-full object-contain"
      onError={() => setFailed(true)}
    />
  );
}

export function PDFPanel({ className, onFileReady, onFileReset }: PDFPanelProps) {
  const [uploadStatus, setUploadStatus] = useState<UploadStatus>('idle');
  const [fileName, setFileName] = useState<string>('');
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(0);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [fileId, setFileId] = useState<string>('');
  const [errorMessage, setErrorMessage] = useState<string>('');
  const [indexingFailed, setIndexingFailed] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const statusPollTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const requestIdRef = useRef(0);

  const stopPolling = () => {
    if (statusPollTimeout.current) clearTimeout(statusPollTimeout.current);
    statusPollTimeout.current = null;
  };

  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.type !== 'application/pdf' && !/\.pdf$/i.test(file.name)) {
      toast.error('请选择 PDF 文件');
      event.target.value = '';
      return;
    }

    stopPolling();
    const requestId = ++requestIdRef.current;
    onFileReset?.();
    setFileName(file.name);
    setUploadStatus('uploading');
    setUploadProgress(0);
    setErrorMessage('');
    setIndexingFailed(false);

    try {
      const uploadResponse = await uploadPdf(file);
      if (requestId !== requestIdRef.current) return;
      setUploadProgress(100);
      setFileId(uploadResponse.fileId);
      setTotalPages(uploadResponse.pages);
      setCurrentPage(1);
      setUploadStatus('parsing');
      setUploadProgress(0);
      await startParse(uploadResponse.fileId);
      if (requestId !== requestIdRef.current) return;
      pollStatus(uploadResponse.fileId, uploadResponse.name, uploadResponse.pages, requestId);
    } catch (error) {
      if (requestId !== requestIdRef.current) return;
      setUploadStatus('error');
      setErrorMessage(error instanceof Error ? error.message : '上传或解析失败');
      toast.error('PDF 处理失败');
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const pollStatus = async (uploadedFileId: string, uploadedName: string, pages: number, requestId: number) => {
    try {
      const status = await getParseStatus(uploadedFileId);
      if (requestId !== requestIdRef.current) return;
      setUploadProgress(status.progress);
      if (status.status === 'ready') {
        setUploadStatus('indexing');
        try {
          await buildIndex(uploadedFileId);
          if (requestId !== requestIdRef.current) return;
          setUploadStatus('ready');
          toast.success('PDF 已解析并建立索引');
          onFileReady?.(uploadedFileId, uploadedName, pages);
        } catch (error) {
          if (requestId !== requestIdRef.current) return;
          setIndexingFailed(true);
          setUploadStatus('error');
          setErrorMessage(error instanceof Error ? error.message : '索引构建失败');
        }
      } else if (status.status === 'error' || status.status === 'idle') {
        setUploadStatus('error');
        setErrorMessage(status.errorMsg || 'PDF 解析失败');
      } else {
        statusPollTimeout.current = setTimeout(() => {
          void pollStatus(uploadedFileId, uploadedName, pages, requestId);
        }, 2000);
      }
    } catch (error) {
      if (requestId !== requestIdRef.current) return;
      setUploadStatus('error');
      setErrorMessage(error instanceof Error ? error.message : '无法获取解析状态');
    }
  };

  const retryIndex = async () => {
    if (!fileId || !indexingFailed) return;
    const requestId = requestIdRef.current;
    setUploadStatus('indexing');
    setErrorMessage('');
    try {
      await buildIndex(fileId);
      if (requestId !== requestIdRef.current) return;
      setIndexingFailed(false);
      setUploadStatus('ready');
      onFileReady?.(fileId, fileName, totalPages);
      toast.success('索引已重建');
    } catch (error) {
      if (requestId !== requestIdRef.current) return;
      setUploadStatus('error');
      setErrorMessage(error instanceof Error ? error.message : '索引构建失败');
    }
  };

  // 清理定时器
  useEffect(() => {
    return () => {
      requestIdRef.current += 1;
      stopPolling();
    };
  }, []);

  const handleUploadClick = () => {
    fileInputRef.current?.click();
  };

  const handleReplace = () => {
    // 清理定时器
    requestIdRef.current += 1;
    stopPolling();
    onFileReset?.();

    setUploadStatus('idle');
    setFileName('');
    setCurrentPage(1);
    setTotalPages(0);
    setUploadProgress(0);
    setFileId('');
    setErrorMessage('');
    setIndexingFailed(false);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const nextPage = () => {
    if (currentPage < totalPages) {
      setCurrentPage(prev => prev + 1);
    }
  };

  const prevPage = () => {
    if (currentPage > 1) {
      setCurrentPage(prev => prev - 1);
    }
  };

  const getStatusIcon = () => {
    switch (uploadStatus) {
      case 'uploading':
      case 'parsing':
      case 'indexing':
        return <Loader2 className="w-4 h-4 animate-spin" />;
      case 'ready':
        return <CheckCircle2 className="w-4 h-4 text-green-500" />;
      case 'error':
        return <AlertCircle className="w-4 h-4 text-red-500" />;
      default:
        return <FileText className="w-4 h-4" />;
    }
  };

  const getStatusText = () => {
    switch (uploadStatus) {
      case 'uploading':
        return 'Uploading...';
      case 'parsing':
        return 'Parsing document...';
      case 'indexing':
        return 'Building index...';
      case 'ready':
        return 'Ready';
      case 'error':
        return 'Error';
      default:
        return 'No document';
    }
  };

  const getStatusVariant = (): "default" | "secondary" | "destructive" | "outline" => {
    switch (uploadStatus) {
      case 'ready':
        return 'default';
      case 'error':
        return 'destructive';
      case 'uploading':
      case 'parsing':
      case 'indexing':
        return 'secondary';
      default:
        return 'outline';
    }
  };

  return (
    <div className={`glass-panel-bright h-full flex flex-col relative overflow-hidden ${className}`}>
      {/* Subtle background pattern */}
      <div className="absolute inset-0 opacity-5">
        <div className="absolute inset-0 bg-gradient-to-br from-green-500/20 via-transparent to-blue-500/20"></div>
      </div>

      {/* Header */}
      <div className="relative p-5 border-b border-border/80">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-green-500/15 border border-green-500/30 shadow-lg">
              <File className="w-5 h-5 text-green-500" />
            </div>
            <div>
              <h2 className="elegant-title text-base">Document</h2>
              <p className="text-xs text-muted-foreground/80 mt-1">PDF Analysis</p>
            </div>
          </div>
          <Badge variant={getStatusVariant()} className="flex items-center gap-2 px-3 py-1 shadow-sm">
            {getStatusIcon()}
            <span className="text-xs">{getStatusText()}</span>
          </Badge>
        </div>

        {uploadStatus === 'idle' ? (
          <Button
            onClick={handleUploadClick}
            className="w-full bg-gradient-to-r from-green-500 to-green-600 hover:from-green-600 hover:to-green-700 text-white shadow-lg border border-green-500/30 rounded-xl transition-all duration-200 min-h-[48px] h-[48px] text-base font-medium cursor-pointer"
          >
            <Upload className="w-5 h-5 mr-2 flex-shrink-0" />
            <span className="flex-shrink-0">Upload PDF</span>
          </Button>
        ) : (
          <div className="flex gap-2">
            <div className="flex-1 text-sm text-muted-foreground truncate bg-secondary/40 p-3 rounded-lg border border-border/40 min-h-[48px] flex items-center">
              {fileName}
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={handleReplace}
              className="shrink-0 min-h-[48px] h-[48px] w-[48px] p-0 border-border/40 hover:bg-destructive/10 transition-all duration-200"
            >
              <RefreshCw className="w-4 h-4" />
            </Button>
          </div>
        )}

        {(uploadStatus === 'uploading' || uploadStatus === 'parsing' || uploadStatus === 'indexing') && (
          <div className="mt-4">
            <Progress value={uploadProgress} className="h-2" />
            <p className="text-xs text-muted-foreground/80 mt-2">
              {uploadStatus === 'uploading' ? '正在上传 PDF…'
                : uploadStatus === 'indexing' ? '正在建立检索索引…'
                : `正在解析 PDF… ${uploadProgress}%`}
            </p>
          </div>
        )}

        {uploadStatus === 'error' && errorMessage && (
          <div className="mt-4 p-3 bg-destructive/10 border border-destructive/30 rounded-lg">
            <p className="text-xs text-destructive">{errorMessage}</p>
            {indexingFailed && (
              <Button variant="outline" size="sm" className="mt-2" onClick={retryIndex}>
                重试建立索引
              </Button>
            )}
          </div>
        )}

        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf"
          onChange={handleFileUpload}
          className="hidden"
        />
      </div>

      {/* Content */}
      {uploadStatus === 'ready' ? (
        <div className="flex-1 flex flex-col relative min-h-0">
          {/* Tabs - 修复超出问题 */}
          <Tabs defaultValue="original" className="flex-1 flex flex-col min-h-0">
            <div className="px-5 pt-4">
              <TabsList className="grid w-full grid-cols-2 h-10 bg-secondary/40 border border-border/40">
                <TabsTrigger value="original" className="text-xs px-2 py-2 data-[state=active]:bg-primary/15 data-[state=active]:text-primary transition-all">
                  Original
                </TabsTrigger>
                <TabsTrigger value="parsed" className="text-xs px-2 py-2 data-[state=active]:bg-primary/15 data-[state=active]:text-primary transition-all">
                  Parsed
                </TabsTrigger>
              </TabsList>
            </div>

            <TabsContent value="original" className="flex-1 flex flex-col mt-4 mx-5 mb-4 min-h-0">
              {/* PDF Viewer */}
              <div className="flex-1 bg-slate-900/40 border border-border/60 rounded-xl flex items-center justify-center shadow-inner overflow-hidden">
                {fileId && <PagePreview key={`${fileId}-${currentPage}-original`} fileId={fileId} page={currentPage} type="original" />}
              </div>
            </TabsContent>

            <TabsContent value="parsed" className="flex-1 flex flex-col mt-4 mx-5 mb-4 min-h-0">
              {/* Parsed Content */}
              <div className="flex-1 bg-slate-900/40 border border-border/60 rounded-xl flex items-center justify-center shadow-inner overflow-hidden">
                {fileId && <PagePreview key={`${fileId}-${currentPage}-parsed`} fileId={fileId} page={currentPage} type="parsed" />}
              </div>
            </TabsContent>
          </Tabs>

          {/* Pagination */}
          <div className="p-5 border-t border-border/60 bg-card/40">
            <div className="flex items-center justify-between">
              <Button
                variant="outline"
                size="sm"
                onClick={prevPage}
                disabled={currentPage <= 1}
                className="h-10 px-4 border-border/40 hover:bg-primary/10 transition-all"
              >
                <ChevronLeft className="w-4 h-4" />
              </Button>

              <span className="text-sm text-muted-foreground font-medium">
                Page {currentPage} of {totalPages}
              </span>

              <Button
                variant="outline"
                size="sm"
                onClick={nextPage}
                disabled={currentPage >= totalPages}
                className="h-10 px-4 border-border/40 hover:bg-primary/10 transition-all"
              >
                <ChevronRight className="w-4 h-4" />
              </Button>
            </div>
          </div>
        </div>
      ) : (
        <div className="flex-1 flex items-center justify-center p-8 relative">
          <div className="text-center space-y-6 max-w-sm">
            {uploadStatus === 'idle' ? (
              <>
                <div className="w-20 h-20 bg-gradient-to-br from-green-500/15 to-blue-500/15 rounded-full flex items-center justify-center mx-auto border border-green-500/30 shadow-lg">
                  <Upload className="w-10 h-10 text-green-500/80" />
                </div>
                <div className="space-y-2">
                  <h3 className="font-semibold text-foreground">No document uploaded</h3>
                  <p className="text-sm text-muted-foreground/80 leading-relaxed">
                    Upload a PDF document to start analyzing and asking questions about its content.
                  </p>
                </div>
              </>
            ) : uploadStatus === 'error' ? (
              <>
                <div className="w-20 h-20 bg-red-500/15 rounded-full flex items-center justify-center mx-auto border border-red-500/30 shadow-lg">
                  <AlertCircle className="w-10 h-10 text-red-500" />
                </div>
                <div className="space-y-2">
                  <h3 className="font-semibold text-foreground">Upload failed</h3>
                  <p className="text-sm text-muted-foreground/80">
                    There was an error processing your document. Please try again.
                  </p>
                </div>
              </>
            ) : (
              <>
                <div className="w-20 h-20 bg-primary/15 rounded-full flex items-center justify-center mx-auto border border-primary/30 shadow-lg">
                  <Loader2 className="w-10 h-10 text-primary animate-spin" />
                </div>
                <div className="space-y-2">
                  <h3 className="font-semibold text-foreground">Processing document</h3>
                  <p className="text-sm text-muted-foreground/80">
                    {uploadStatus === 'uploading'
                      ? 'Uploading your PDF file...'
                      : 'Analyzing and parsing the document content...'}
                  </p>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
