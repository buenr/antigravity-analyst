import React, { useState, useEffect } from 'react';
import { Database, Loader2, Trash2, FileUp, MessageSquare, Download } from 'lucide-react';
import FileUpload from './components/FileUpload';
import ChatInterface from './components/ChatInterface';
import FileDownload from './components/FileDownload';
import { createSession, getSession, listFiles } from './services/api';

/**
 * Main application component.
 */
function App() {
  const [sessionId, setSessionId] = useState(null);
  const [session, setSession] = useState(null);
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('upload');
  const [briefRequestId, setBriefRequestId] = useState(0);

  // Load session from localStorage on mount
  useEffect(() => {
    const savedSessionId = localStorage.getItem('antigravity_session_id');
    if (savedSessionId) {
      loadSession(savedSessionId);
    }
  }, []);

  const loadSession = async (id) => {
    try {
      const sessionData = await getSession(id);
      setSessionId(id);
      setSession(sessionData);
      const fileData = await listFiles(id);
      setFiles(fileData.files || []);
    } catch (err) {
      // Session not found, clear localStorage
      localStorage.removeItem('antigravity_session_id');
    }
  };

  const handleCreateSession = async () => {
    setLoading(true);
    setError(null);

    try {
      const sessionData = await createSession('default');
      setSessionId(sessionData.session_id);
      setSession(sessionData);
      setFiles([]);
      localStorage.setItem('antigravity_session_id', sessionData.session_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteSession = () => {
    setSessionId(null);
    setSession(null);
    setFiles([]);
    localStorage.removeItem('antigravity_session_id');
  };

  const handleUploadComplete = (file) => {
    const shouldGenerateBrief = files.length === 0;
    setFiles((prev) => [...prev, file]);
    if (shouldGenerateBrief) {
      setBriefRequestId((id) => id + 1);
    }
    setActiveTab('chat');
  };

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 py-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Database className="w-8 h-8 text-primary-600" />
              <div>
                <h1 className="text-xl font-bold text-gray-900">
                  Antigravity Data Analyst
                </h1>
                <p className="text-sm text-gray-500">
                  AI-powered data analysis with Gemini
                </p>
              </div>
            </div>

            {session && (
              <div className="flex items-center gap-3">
                <div className="text-right text-sm">
                  <p className="text-gray-500">Session</p>
                  <p className="font-mono text-xs text-gray-400">
                    {sessionId?.slice(0, 8)}...
                  </p>
                </div>
                <button
                  onClick={handleDeleteSession}
                  className="p-2 text-gray-400 hover:text-red-500 transition-colors"
                  title="Delete session"
                >
                  <Trash2 className="w-5 h-5" />
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 py-6 sm:px-6 lg:px-8">
        {!session ? (
          /* No Session - Show Create Button */
          <div className="flex flex-col items-center justify-center py-16">
            <Database className="w-24 h-24 text-gray-300 mb-6" />
            <h2 className="text-2xl font-bold text-gray-800 mb-2">
              Welcome to Antigravity Data Analyst
            </h2>
            <p className="text-gray-500 mb-8 text-center max-w-md">
              Create a session to start analyzing your data with AI. 
              Upload CSV or Excel files and ask questions about your data.
            </p>

            {error && (
              <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 rounded-lg">
                {error}
              </div>
            )}

            <button
              onClick={handleCreateSession}
              disabled={loading}
              className="flex items-center gap-2 px-6 py-3 bg-primary-600 text-white rounded-lg font-medium hover:bg-primary-700 transition-colors disabled:opacity-50"
            >
              {loading ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  Creating Session...
                </>
              ) : (
                <>
                  <Database className="w-5 h-5" />
                  Create New Session
                </>
              )}
            </button>
          </div>
        ) : (
          /* Active Session - Show Tabs and Content */
          <div className="space-y-6">
            {/* Tab Navigation */}
            <div className="border-b border-gray-200">
              <nav className="flex gap-8">
                <button
                  onClick={() => setActiveTab('upload')}
                  className={`flex items-center gap-2 pb-3 px-1 border-b-2 font-medium text-sm transition-colors
                    ${activeTab === 'upload'
                      ? 'border-primary-500 text-primary-600'
                      : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                    }`}
                >
                  <FileUp className="w-4 h-4" />
                  Upload Files
                </button>
                <button
                  onClick={() => setActiveTab('chat')}
                  className={`flex items-center gap-2 pb-3 px-1 border-b-2 font-medium text-sm transition-colors
                    ${activeTab === 'chat'
                      ? 'border-primary-500 text-primary-600'
                      : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                    }`}
                >
                  <MessageSquare className="w-4 h-4" />
                  Chat
                  {files.length === 0 && (
                    <span className="text-xs text-gray-400">(upload files first)</span>
                  )}
                </button>
                <button
                  onClick={() => setActiveTab('reports')}
                  className={`flex items-center gap-2 pb-3 px-1 border-b-2 font-medium text-sm transition-colors
                    ${activeTab === 'reports'
                      ? 'border-primary-500 text-primary-600'
                      : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                    }`}
                >
                  <Download className="w-4 h-4" />
                  Reports
                </button>
              </nav>
            </div>

            {/* Tab Content */}
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
              {activeTab === 'upload' && (
                <FileUpload
                  sessionId={sessionId}
                  onUploadComplete={handleUploadComplete}
                />
              )}

              {activeTab === 'chat' && (
                <div className="h-[600px]">
                  <ChatInterface
                    sessionId={sessionId}
                    hasFiles={files.length > 0}
                    briefRequestId={briefRequestId}
                  />
                </div>
              )}

              {activeTab === 'reports' && (
                <FileDownload sessionId={sessionId} />
              )}
            </div>
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="fixed bottom-0 w-full bg-white border-t border-gray-200 py-3">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <p className="text-center text-sm text-gray-500">
            Powered by Gemini Antigravity Agent • 
            <a
              href="https://ai.google.dev/gemini-api/docs/managed-agents-quickstart"
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary-600 hover:text-primary-700 ml-1"
            >
              Documentation
            </a>
          </p>
        </div>
      </footer>
    </div>
  );
}

export default App;
