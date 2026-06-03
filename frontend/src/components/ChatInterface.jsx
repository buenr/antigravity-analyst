import React, { useState, useRef, useEffect, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import {
  Send,
  Loader2,
  User,
  Bot,
  AlertCircle,
  X,
  Download,
  FileText,
  FileImage,
  FileSpreadsheet,
  ExternalLink,
  Paperclip,
} from 'lucide-react';
import { useStreamingChat } from '../hooks/useSSE';
import {
  fileToImageInput,
  generateBrief,
  getChatHistory,
  getReportDownloadUrl,
  reportBasename,
  apiReportPath,
} from '../services/api';
import AgentActivity from './AgentActivity';
import UsageBadge from './UsageBadge';

const MAX_INLINE_IMAGES = 4;
const MAX_INLINE_IMAGE_BYTES = 5 * 1024 * 1024;

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
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [briefLoading, setBriefLoading] = useState(false);
  const [briefError, setBriefError] = useState(null);
  const [pendingImages, setPendingImages] = useState([]);
  const [imageError, setImageError] = useState(null);
  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);
  const handledBriefRequestRef = useRef(0);

  const { isStreaming, events, startStream, stopStream, error } = useStreamingChat();

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
              usage: message.usage || null,
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
              usage: brief.usage || null,
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
  }, [messages, events, briefLoading]);

  // Process streaming events - only handle errors here, completion is rendered inline
  useEffect(() => {
    if (events.length === 0) return;
    const latestEvent = events[events.length - 1];

    if (latestEvent.event_type === 'error') {
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now(),
          role: 'error',
          content: latestEvent.message,
        },
      ]);
    }
  }, [events]);

  const handleImagePick = async (fileList) => {
    setImageError(null);
    const files = Array.from(fileList || []);
    if (files.length === 0) return;

    const remaining = MAX_INLINE_IMAGES - pendingImages.length;
    if (remaining <= 0) {
      setImageError(`You can attach at most ${MAX_INLINE_IMAGES} images per message.`);
      return;
    }
    const accepted = files.slice(0, remaining);

    const next = [];
    for (const file of accepted) {
      if (!file.type.startsWith('image/')) {
        setImageError(`${file.name} is not an image.`);
        continue;
      }
      if (file.size > MAX_INLINE_IMAGE_BYTES) {
        setImageError(`${file.name} exceeds 5 MB.`);
        continue;
      }
      try {
        const img = await fileToImageInput(file);
        next.push({ ...img, _name: file.name, _previewUrl: URL.createObjectURL(file) });
      } catch (err) {
        setImageError(err.message || 'Failed to read image');
      }
    }
    if (next.length > 0) {
      setPendingImages((prev) => [...prev, ...next]);
    }
  };

  const removePendingImage = (index) => {
    setPendingImages((prev) => {
      const next = [...prev];
      const [removed] = next.splice(index, 1);
      if (removed?._previewUrl) URL.revokeObjectURL(removed._previewUrl);
      return next;
    });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    if ((!input.trim() && pendingImages.length === 0) || isStreaming || briefLoading) return;

    const imagesPayload = pendingImages.map(({ data, mime_type }) => ({ data, mime_type }));
    const userMessage = {
      id: Date.now(),
      role: 'user',
      content: input,
      images: pendingImages.map(({ _previewUrl, _name }) => ({ _previewUrl, _name })),
    };
    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setPendingImages([]);
    setImageError(null);

    await startStream(sessionId, userMessage.content, imagesPayload);
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
                <>
                  {msg.images?.length > 0 && (
                    <div className="flex flex-wrap gap-2 mb-2">
                      {msg.images.map((img, idx) => (
                        <img
                          key={idx}
                          src={img._previewUrl}
                          alt={img._name || 'attachment'}
                          className="w-20 h-20 object-cover rounded-md border border-primary-400"
                        />
                      ))}
                    </div>
                  )}
                  {msg.content && (
                    <p className="whitespace-pre-wrap">{msg.content}</p>
                  )}
                </>
              ) : (
                <>
                  <div className="markdown-content prose prose-sm max-w-none">
                    <ReactMarkdown components={markdownComponents}>
                      {msg.content}
                    </ReactMarkdown>
                  </div>
                  {msg.role === 'assistant' && (
                    <>
                      <MessageAttachments
                        sessionId={sessionId}
                        attachments={msg.attachments}
                      />
                      <UsageBadge usage={msg.usage} />
                    </>
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

        {(isStreaming || events.length > 0) && (
          <>
            <div className="flex gap-3">
              <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary-100 flex items-center justify-center">
                <Bot className="w-5 h-5 text-primary-600" />
              </div>
              <div className="flex-1 min-w-0">
                <AgentActivity events={events} isStreaming={isStreaming} />
              </div>
            </div>
            {events.some(
              (ev) => ev.event_type === 'complete' && ev.message
            ) && (
              <div className="flex gap-3">
                <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary-100 flex items-center justify-center">
                  <Bot className="w-5 h-5 text-primary-600" />
                </div>
                <div className="max-w-[80%] rounded-lg p-4 bg-white border border-gray-200">
                  <div className="markdown-content prose prose-sm max-w-none">
                    <ReactMarkdown components={markdownComponents}>
                      {events.find((ev) => ev.event_type === 'complete')?.message || ''}
                    </ReactMarkdown>
                  </div>
                  {events.find((ev) => ev.event_type === 'complete')?.data?.reports && (
                    <MessageAttachments
                      sessionId={sessionId}
                      attachments={events.find((ev) => ev.event_type === 'complete').data.reports}
                    />
                  )}
                  {events.find((ev) => ev.event_type === 'complete')?.data?.usage && (
                    <UsageBadge usage={events.find((ev) => ev.event_type === 'complete').data.usage} />
                  )}
                </div>
              </div>
            )}
          </>
        )}

        <div ref={messagesEndRef} />
      </div>

      <div className="border-t border-gray-200 p-4 bg-white">
        {pendingImages.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-2">
            {pendingImages.map((img, idx) => (
              <div
                key={idx}
                className="relative group w-16 h-16 rounded-md overflow-hidden border border-gray-300"
              >
                <img
                  src={img._previewUrl}
                  alt={img._name}
                  className="w-full h-full object-cover"
                />
                <button
                  type="button"
                  onClick={() => removePendingImage(idx)}
                  className="absolute top-0.5 right-0.5 p-0.5 rounded-full bg-black/60 text-white opacity-0 group-hover:opacity-100 transition-opacity"
                  aria-label={`Remove ${img._name}`}
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
        )}
        {imageError && (
          <div className="mb-2 text-xs text-red-600">{imageError}</div>
        )}
        <form onSubmit={handleSubmit} className="flex gap-2 items-center">
          <input
            ref={fileInputRef}
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            multiple
            className="hidden"
            onChange={(e) => {
              handleImagePick(e.target.files);
              e.target.value = '';
            }}
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={isStreaming || briefLoading || !hasFiles}
            className="p-2 text-gray-500 hover:text-primary-600 disabled:opacity-50 disabled:cursor-not-allowed"
            title="Attach image"
          >
            <Paperclip className="w-5 h-5" />
          </button>
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
              disabled={
                briefLoading ||
                !hasFiles ||
                (!input.trim() && pendingImages.length === 0)
              }
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
