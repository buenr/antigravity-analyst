import React, { useState, useEffect } from 'react';
import { Download, FileText, FileImage, FileSpreadsheet, RefreshCw } from 'lucide-react';
import { listReports } from '../services/api';

/**
 * Component for listing and downloading generated reports.
 */
export default function FileDownload({ sessionId }) {
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const loadReports = async () => {
    if (!sessionId) return;
    
    setLoading(true);
    setError(null);
    
    try {
      const result = await listReports(sessionId);
      setReports(result.reports || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadReports();
  }, [sessionId]);

  const getFileIcon = (fileType) => {
    switch (fileType) {
      case '.pdf':
        return <FileText className="w-5 h-5 text-red-500" />;
      case '.png':
      case '.jpg':
      case '.jpeg':
        return <FileImage className="w-5 h-5 text-green-500" />;
      case '.csv':
      case '.xlsx':
        return <FileSpreadsheet className="w-5 h-5 text-blue-500" />;
      default:
        return <FileText className="w-5 h-5 text-gray-500" />;
    }
  };

  const formatFileSize = (bytes) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const handleDownload = (fileName) => {
    const url = `/api/chat/${sessionId}/reports/${fileName}`;
    window.open(url, '_blank');
  };

  if (reports.length === 0 && !loading) {
    return null;
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-gray-800">Generated Reports</h3>
        <button
          onClick={loadReports}
          disabled={loading}
          className="text-primary-600 hover:text-primary-700 text-sm flex items-center gap-1"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 p-3 rounded-lg text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-center py-4 text-gray-500">
          Loading reports...
        </div>
      ) : (
        <ul className="space-y-2">
          {reports.map((report, idx) => (
            <li
              key={idx}
              className="flex items-center justify-between bg-white border border-gray-200 rounded-lg p-3 hover:border-primary-300 transition-colors"
            >
              <div className="flex items-center gap-3">
                {getFileIcon(report.file_type)}
                <div>
                  <p className="font-medium text-gray-800">{report.file_name}</p>
                  <p className="text-sm text-gray-500">
                    {formatFileSize(report.size_bytes)}
                  </p>
                </div>
              </div>
              <button
                onClick={() => handleDownload(report.file_name)}
                className="flex items-center gap-1 px-3 py-1.5 bg-primary-50 text-primary-600 rounded-lg hover:bg-primary-100 transition-colors text-sm font-medium"
              >
                <Download className="w-4 h-4" />
                Download
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
