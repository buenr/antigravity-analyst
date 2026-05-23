import React, { useCallback, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { Upload, FileText, X, Loader2 } from 'lucide-react';
import { uploadFile, listFiles, downloadFile } from '../services/api';

/**
 * File upload component with drag-and-drop support.
 */
export default function FileUpload({ sessionId, onUploadComplete }) {
  const [files, setFiles] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(null);
  const [error, setError] = useState(null);

  // Load existing files on mount
  React.useEffect(() => {
    if (sessionId) {
      loadFiles();
    }
  }, [sessionId]);

  const loadFiles = async () => {
    try {
      const result = await listFiles(sessionId);
      setFiles(result.files || []);
    } catch (err) {
      console.error('Failed to load files:', err);
    }
  };

  const onDrop = useCallback(
    async (acceptedFiles) => {
      if (!sessionId) {
        setError('Please create a session first');
        return;
      }

      setUploading(true);
      setError(null);

      for (const file of acceptedFiles) {
        try {
          setUploadProgress(file.name);
          const result = await uploadFile(sessionId, file);
          setFiles((prev) => [...prev, result]);
          
          if (onUploadComplete) {
            onUploadComplete(result);
          }
        } catch (err) {
          setError(err.message);
        }
      }

      setUploading(false);
      setUploadProgress(null);
    },
    [sessionId, onUploadComplete]
  );

  const handleDownload = async (fileId, filename) => {
    try {
      const blob = await downloadFile(fileId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.message);
    }
  };

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'text/csv': ['.csv'],
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
      'application/vnd.ms-excel': ['.xls'],
    },
    maxSize: 50 * 1024 * 1024, // 50MB
  });

  return (
    <div className="space-y-4">
      {/* Dropzone */}
      <div
        {...getRootProps()}
        className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors
          ${isDragActive
            ? 'border-primary-500 bg-primary-50'
            : 'border-gray-300 hover:border-primary-400 hover:bg-gray-50'
          }`}
      >
        <input {...getInputProps()} />
        <Upload className="w-12 h-12 mx-auto mb-4 text-gray-400" />
        {isDragActive ? (
          <p className="text-primary-600 font-medium">Drop files here...</p>
        ) : (
          <div>
            <p className="text-gray-600 font-medium">
              Drag & drop CSV or Excel files here
            </p>
            <p className="text-sm text-gray-500 mt-1">
              or click to browse (max 50MB)
            </p>
          </div>
        )}
      </div>

      {/* Upload Progress */}
      {uploading && (
        <div className="flex items-center gap-2 text-primary-600 bg-primary-50 p-3 rounded-lg">
          <Loader2 className="w-4 h-4 animate-spin" />
          <span>Uploading {uploadProgress}...</span>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 p-3 rounded-lg flex items-center gap-2">
          <X className="w-4 h-4" />
          <span>{error}</span>
        </div>
      )}

      {/* File List */}
      {files.length > 0 && (
        <div className="space-y-2">
          <h3 className="font-medium text-gray-700">Uploaded Files</h3>
          <ul className="space-y-2">
            {files.map((file) => (
              <li
                key={file.file_id}
                className="flex items-center justify-between bg-white border border-gray-200 rounded-lg p-3"
              >
                <div className="flex items-center gap-3">
                  <FileText className="w-5 h-5 text-primary-500" />
                  <div>
                    <p className="font-medium text-gray-800">
                      {file.original_filename}
                    </p>
                    <p className="text-sm text-gray-500">{file.file_size}</p>
                  </div>
                </div>
                <button
                  onClick={() => handleDownload(file.file_id, file.original_filename)}
                  className="text-primary-600 hover:text-primary-700 text-sm font-medium"
                >
                  Download
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
