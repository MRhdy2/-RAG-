import { useState } from "react";
import { Header } from "./components/Header";
import { ChatInterface } from "./components/ChatInterface";
import { PDFPanel } from "./components/PDFPanel";
import { Toaster } from "./components/ui/sonner";

export default function App() {
  const [currentFileId, setCurrentFileId] = useState<string>('');
  const [currentFileName, setCurrentFileName] = useState<string>('');

  const handleFileReady = (fileId: string, fileName: string) => {
    setCurrentFileId(fileId);
    setCurrentFileName(fileName);
  };

  const handleFileReset = () => {
    setCurrentFileId('');
    setCurrentFileName('');
  };

  return (
    <div className="dark min-h-screen bg-background text-foreground relative overflow-x-hidden">
      {/* Enhanced background system */}
      <div className="background-system">
        {/* Floating orbs */}
        <div className="floating-elements">
          <div className="floating-orb floating-orb-1"></div>
          <div className="floating-orb floating-orb-2"></div>
          <div className="floating-orb floating-orb-3"></div>
          <div className="floating-orb floating-orb-4"></div>
        </div>

        {/* Geometric decorations */}
        <div className="geometric-decorations">
          <div className="geometric-line geometric-line-1"></div>
          <div className="geometric-line geometric-line-2"></div>
          <div className="geometric-line geometric-line-3"></div>
          <div className="geometric-polygon geometric-polygon-1"></div>
          <div className="geometric-polygon geometric-polygon-2"></div>
          <div className="geometric-circle geometric-circle-1"></div>
          <div className="geometric-circle geometric-circle-2"></div>
        </div>

        {/* Particle system */}
        <div className="particle-system">
          {Array.from({ length: 15 }).map((_, i) => (
            <div key={i} className={`particle particle-${i + 1}`}></div>
          ))}
        </div>

        {/* Light beams */}
        <div className="light-beams">
          <div className="light-beam light-beam-1"></div>
          <div className="light-beam light-beam-2"></div>
          <div className="light-beam light-beam-3"></div>
        </div>

        {/* Grid overlay */}
        <div className="grid-overlay"></div>
      </div>

      <div className="relative z-10">
        <div className="min-h-screen lg:h-screen flex flex-col">
          {/* Header with reduced bottom margin */}
          <div className="max-w-7xl mx-auto w-full">
            <Header />
          </div>

          {/* Main Content - Consistent spacing layout */}
          <div className="grid grid-cols-1 lg:grid-cols-[1.5fr_1fr] gap-4 lg:gap-6 lg:flex-1 lg:min-h-0 px-4 lg:px-6 pb-6">
            {/* Left Column - Chat Interface (larger) */}
            <div className="flex flex-col h-[65vh] min-h-[420px] lg:h-auto lg:min-h-0">
              <ChatInterface
                key={currentFileId || 'no-document'}
                fileId={currentFileId}
                fileName={currentFileName}
                threadId={currentFileId || 'default'}
              />
            </div>

            {/* Right Column - PDF Panel (smaller, aligned to right edge) */}
            <div className="flex flex-col h-[70vh] min-h-[450px] lg:h-auto lg:min-h-0">
              <PDFPanel
                onFileReady={handleFileReady}
                onFileReset={handleFileReset}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Toast notifications */}
      <Toaster
        position="top-right"
        expand={false}
        richColors
        closeButton
        theme="dark"
      />
    </div>
  );
}
