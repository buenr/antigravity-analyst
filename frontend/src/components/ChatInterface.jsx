import React, { useState, useRef, useEffect, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import {
  Send,
  Loader2,
  User,
  Bot,
  Terminal,
  CheckCircle,
  AlertCircle,
  X,
  Download,
  FileText,
  FileImage,
  FileSpreadsheet,
  ExternalLink,
} from 'lucide-react';
import { useStreamingChat } from '../hooks/useSSE';
import {
  generateBrief,
  getChatHistory,
  getReportDownloadUrl,
  reportBasename,
  apiReportPath,
} from '../services/api';

const IMAGE_EXTENSIONS = new Set(['.png', '.jpg', '.jpeg']);

function getFileIcon(fileType) {
  switch (fileType) {
    case '.pdf':
      return <FileText className="w-4 h-4 text-red-500" />;
    case '.png':
    case '.jpg':
    case '.jpeg':
      return <FileImage className="w-4 h-4 text-green-500" />;
    case '.csv':
    case '.xlsx':
      return <FileSpreadsheet className="w-4 h-4 text-blue-500" />;
    default:
      return <FileText className="w-4 h-4 text-gray-500" />;
  }
}

function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function resolveReportHref(sessionId, href) {
  if (!href || href.startsWith('http') || href.startsWith('/api/')) {
    return href;
  }
  if (href.startsWith('/chat/')) {
    return apiReportPath(href);
  }
  const basename = reportBasename(href);
  if (!basename) return href;
  return getReportDownloadUrl(sessionId, basename);
}

function MessageAttachments({ sessionId, attachments }) {
  if (!attachments?.length) return null;

  return (
    <div className="mt-3 pt-3 border-t border-gray-100 space-y-2">
      <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">
        Downloads
      </p>
      <ul className="space-y-2">
        {attachments.map((report) => {
          const downloadUrl = report.download_url
            ? apiReportPath(report.download_url)
            : getReportDownloadUrl(sessionId, report.file_name);
          const previewUrl = IMAGE_EXTENSIONS.has(report.file_type)
            ? getReportDownloadUrl(sessionId, report.file_name, { inline: true })
            : null;

          return (
            <li
              key={report.file_name}
              className="flex flex-wrap items-center justify-between gap-2 bg-gray-50 border border-gray-200 rounded-lg px-3 py-2"
            >
              <div className="flex items-center gap-2 min-w-0">
                {getFileIcon(report.file_type)}
                <div className="min-w-0">
                  <p className="text-sm font-medium text-gray-800 truncate">
                    {report.file_name}
                  </p>
                  <p className="text-xs text-gray-500">
                    {formatFileSize(report.size_bytes || 0)}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {previewUrl && (
                  <a
                    href={previewUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1 px-2 py-1 text-xs text-gray-600 hover:text-primary-600"
                  >
                    <ExternalLink className="w-3.5 h-3.5" />
                    Preview
                  </a>
                )}
                <a
                  href={downloadUrl}
                  download={report.file_name}
                  className="flex items-center gap-1 px-3 py-1.5 bg-primary-50 text-primary-600 rounded-lg hover:bg-primary-100 text-sm font-medium"
                >
                  <Download className="w-4 h-4" />
                  Download
                </a>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/**
 * Chat interface component with streaming support.
 */
export default function ChatInterface({ sessionId, hasFiles, briefRequestId = 0 }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [streamingOutput, setStreamingOutput] = useState('');
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [briefLoading, setBriefLoading] = useState(false);
  const [briefError, setBriefError] = useState(null);
  const messagesEndRef = useRef(null);
  const handledBriefRequestRef = useRef(0);

  const { isStreaming, events, startStream, stopStream, error } = useStreamingChat();
  const [terminalExpanded, setTerminalExpanded] = useState(false);

  const markdownComponents = useMemo(
    () => ({
      img: ({ src, alt, ...props }) => {
        const basename = reportBasename(src);
        const fullSrc = src?.startsWith('http')
          ? src
          : getReportDownloadUrl(sessionId, basename || src, { inline: true });
        return (
          <img
            src={fullSrc}
            alt={alt || 'Chart'}
            className="max-w-full rounded-lg border border-gray-200"
            {...props}
          />
        );
      },
      a: ({ href, children, ...props }) => (
        <a
          href={resolveReportHref(sessionId, href)}
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary-600 hover:text-primary-700 underline"
          {...props}
        >
          {children}
        </a>
      ),
    }),
    [sessionId]
  );

  useEffect(() => {
    let ignore = false;

    async function loadHistory() {
      if (!sessionId) return;

      setHistoryLoaded(false);
      setBriefError(null);

      try {
        const history = await getChatHistory(sessionId);
        if (!ignore) {
          setMessages(
            history.map((message) => ({
              id: message.message_id,
              role: message.role,
              content: message.content,
              attachments: message.attachments || [],
            }))
          );
        }
      } catch (err) {
        if (!ignore) {
          setBriefError(err.message);
        }
      } finally {
        if (!ignore) {
          setHistoryLoaded(true);
        }
      }
    }

    loadHistory();

    return () => {
      ignore = true;
    };
  }, [sessionId]);

  useEffect(() => {
    if (
      !sessionId ||
      !hasFiles ||
      !historyLoaded ||
      !briefRequestId ||
      handledBriefRequestRef.current === briefRequestId ||
      messages.some((message) => message.role === 'assistant')
    ) {
      return;
    }

    let ignore = false;
    handledBriefRequestRef.current = briefRequestId;
    setBriefLoading(true);
    setBriefError(null);

    async function runBrief() {
      try {
        const brief = await generateBrief(sessionId);
        if (!ignore) {
          setMessages((prev) => [
            ...prev,
            {
              id: brief.message_id,
              role: brief.role,
              content: brief.content,
              attachments: brief.attachments || [],
            },
          ]);
        }
      } catch (err) {
        if (!ignore) {
          setBriefError(err.message);
        }
      } finally {
        if (!ignore) {
          setBriefLoading(false);
        }
      }
    }

    runBrief();

    return () => {
      ignore = true;
    };
  }, [briefRequestId, hasFiles, historyLoaded, messages, sessionId]);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingOutput, events, briefLoading]);

  // Process streaming events
  useEffect(() => {
    if (events.length > 0) {
      const latestEvent = events[events.length - 1];

      if (latestEvent.event_type === 'terminal') {
        setStreamingOutput((prev) => prev + latestEvent.message + '\n');
      } else if (latestEvent.event_type === 'complete') {
        setMessages((prev) => [
          ...prev,
          {
            id: Date.now(),
            role: 'assistant',
            content: latestEvent.message,
            attachments: latestEvent.data?.reports || [],
          },
        ]);
        setStreamingOutput('');
        setTerminalExpanded(false);
      } else if (latestEvent.event_type === 'error') {
        setMessages((prev) => [
          ...prev,
          {
            id: Date.now(),
            role: 'error',
            content: latestEvent.message,
          },
        ]);
        setStreamingOutput('');
      }
    }
  }, [events]);

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (!input.trim() || isStreaming || briefLoading) return;

    const userMessage = {
      id: Date.now(),
      role: 'user',
      content: input,
    };
    setMessages((prev) => [...prev, userMessage]);
    setInput('');

    await startStream(sessionId, input);
  };

  const renderEventIcon = (eventType) => {
    switch (eventType) {
      case 'terminal':
      case 'code_execution':
        return <Terminal className="w-4 h-4 text-yellow-500" />;
      case 'complete':
        return <CheckCircle className="w-4 h-4 text-green-500" />;
      case 'error':
        return <AlertCircle className="w-4 h-4 text-red-500" />;
      default:
        return <Bot className="w-4 h-4 text-primary-500" />;
    }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && !isStreaming && !briefLoading && (
          <div className="text-center text-gray-500 mt-8">
            <Bot className="w-16 h-16 mx-auto mb-4 text-gray-300" />
            <p className="text-lg font-medium">Start a conversation</p>
            <p className="text-sm mt-2">
              {hasFiles
                ? 'Ask me to analyze your uploaded data, create visualizations, or generate reports.'
                : 'Upload some data files first, then ask me to analyze them.'}
            </p>
          </div>
        )}

        {briefLoading && (
          <div className="flex gap-3">
            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary-100 flex items-center justify-center">
              <Loader2 className="w-5 h-5 text-primary-600 animate-spin" />
            </div>
            <div className="bg-primary-50 border border-primary-100 text-primary-700 rounded-lg p-4">
              Preparing analyst brief...
            </div>
          </div>
        )}

        {(briefError || error) && (
          <div className="flex gap-3">
            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-red-100 flex items-center justify-center">
              <AlertCircle className="w-5 h-5 text-red-500" />
            </div>
            <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg p-4">
              {briefError || error}
            </div>
          </div>
        )}

        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex gap-3 ${
              msg.role === 'user' ? 'justify-end' : 'justify-start'
            }`}
          >
            {msg.role !== 'user' && (
              <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary-100 flex items-center justify-center">
                {msg.role === 'error' ? (
                  <AlertCircle className="w-5 h-5 text-red-500" />
                ) : (
                  <Bot className="w-5 h-5 text-primary-600" />
                )}
              </div>
            )}
            <div
              className={`max-w-[80%] rounded-lg p-4 ${
                msg.role === 'user'
                  ? 'bg-primary-600 text-white'
                  : msg.role === 'error'
                  ? 'bg-red-50 border border-red-200 text-red-700'
                  : 'bg-white border border-gray-200'
              }`}
            >
              {msg.role === 'user' ? (
                <p className="whitespace-pre-wrap">{msg.content}</p>
              ) : (
                <>
                  <div className="markdown-content prose prose-sm max-w-none">
                    <ReactMarkdown components={markdownComponents}>
                      {msg.content}
                    </ReactMarkdown>
                  </div>
                  {msg.role === 'assistant' && (
                    <MessageAttachments
                      sessionId={sessionId}
                      attachments={msg.attachments}
                    />
                  )}
                </>
              )}
            </div>
            {msg.role === 'user' && (
              <div className="flex-shrink-0 w-8 h-8 rounded-full bg-gray-100 flex items-center justify-center">
                <User className="w-5 h-5 text-gray-600" />
              </div>
            )}
          </div>
        ))}

        {(isStreaming || streamingOutput) && (
          <div className="flex gap-3">
            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary-100 flex items-center justify-center">
              <Loader2 className="w-5 h-5 text-primary-600 animate-spin" />
            </div>
            <div className="flex-1">
              <details
                className="bg-gray-900 text-gray-100 rounded-lg font-mono text-sm overflow-x-auto"
                open={terminalExpanded}
              >
                <summary
                  className="flex items-center gap-2 p-3 cursor-pointer list-none select-none text-primary-400 hover:text-primary-300"
                  onClick={() => setTerminalExpanded(!terminalExpanded)}
                >
                  <Terminal className="w-4 h-4 flex-shrink-0" />
                  <span>Agent executing... (click to expand)</span>
                </summary>
                <div className="px-4 pb-4">
                  <pre className="whitespace-pre-wrap text-green-400">
                    {streamingOutput || 'Initializing sandbox...'}
                  </pre>
                </div>
              </details>
            </div>
          </div>
        )}

        {isStreaming && events.length > 0 && (
          <div className="space-y-1">
            {events.slice(-5).map((event, idx) => (
              <div
                key={idx}
                className="flex items-center gap-2 text-sm text-gray-500"
              >
                {renderEventIcon(event.event_type)}
                <span>{event.event_type}:</span>
                <span className="truncate">{event.message?.slice(0, 100)}</span>
              </div>
            ))}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <div className="border-t border-gray-200 p-4 bg-white">
        <form onSubmit={handleSubmit} className="flex gap-3">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={
              hasFiles
                ? 'Ask me to analyze your data...'
                : 'Upload files first to start analysis...'
            }
            disabled={isStreaming || briefLoading || !hasFiles}
            className="flex-1 border border-gray-300 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent disabled:bg-gray-100 disabled:cursor-not-allowed"
          />
          {isStreaming ? (
            <button
              type="button"
              onClick={stopStream}
              className="px-4 py-2 bg-red-600 text-white rounded-lg font-medium hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 transition-colors flex items-center gap-2"
            >
              <X className="w-4 h-4" />
              <span>Cancel</span>
            </button>
          ) : (
            <button
              type="submit"
              disabled={briefLoading || !input.trim() || !hasFiles}
              className="px-6 py-2 bg-primary-600 text-white rounded-lg font-medium hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <Send className="w-5 h-5" />
            </button>
          )}
        </form>
      </div>
    </div>
  );
}
