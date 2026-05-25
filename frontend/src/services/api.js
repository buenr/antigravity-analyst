/**
 * API service for communicating with the backend.
 */

const API_BASE = '/api';

/**
 * Parse error response from the server.
 * Handles both JSON and non-JSON (HTML) error responses.
 * @param {Response} response - Fetch response object
 * @returns {Promise<string>} Error message
 */
async function parseErrorResponse(response) {
  const contentType = response.headers.get('content-type') || '';
  
  if (contentType.includes('application/json')) {
    try {
      const error = await response.json();
      return error.detail || `Error: ${response.status} ${response.statusText}`;
    } catch {
      return `Error: ${response.status} ${response.statusText}`;
    }
  }
  
  // Non-JSON response (likely HTML error page)
  const text = await response.text();
  // Extract meaningful error from HTML or provide generic message
  if (text.includes('Internal Server Error')) {
    return `Server error (${response.status}): Please check server logs for details`;
  }
  return `Error: ${response.status} ${response.statusText}`;
}

/**
 * Create a new session.
 * @param {string} tenantId - Optional tenant ID
 * @returns {Promise<Object>} Session data
 */
export async function createSession(tenantId = 'default') {
  const response = await fetch(`${API_BASE}/sessions/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tenant_id: tenantId }),
  });
  
  if (!response.ok) {
    const errorMessage = await parseErrorResponse(response);
    throw new Error(errorMessage);
  }
  
  return response.json();
}

/**
 * Get session details.
 * @param {string} sessionId - Session ID
 * @returns {Promise<Object>} Session data
 */
export async function getSession(sessionId) {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}`);
  
  if (!response.ok) {
    const errorMessage = await parseErrorResponse(response);
    throw new Error(errorMessage);
  }
  
  return response.json();
}

/**
 * Upload a file to a session.
 * @param {string} sessionId - Session ID
 * @param {File} file - File to upload
 * @returns {Promise<Object>} Upload result
 */
export async function uploadFile(sessionId, file) {
  const formData = new FormData();
  formData.append('file', file);
  
  const response = await fetch(`${API_BASE}/files/upload/${sessionId}`, {
    method: 'POST',
    body: formData,
  });
  
  if (!response.ok) {
    const errorMessage = await parseErrorResponse(response);
    throw new Error(errorMessage);
  }
  
  return response.json();
}

/**
 * List files in a session.
 * @param {string} sessionId - Session ID
 * @returns {Promise<Object>} File list
 */
export async function listFiles(sessionId) {
  const response = await fetch(`${API_BASE}/files/${sessionId}`);
  
  if (!response.ok) {
    const errorMessage = await parseErrorResponse(response);
    throw new Error(errorMessage);
  }
  
  return response.json();
}

/**
 * Download a file.
 * @param {string} fileId - File ID
 * @returns {Promise<Blob>} File blob
 */
export async function downloadFile(fileId) {
  const response = await fetch(`${API_BASE}/files/download/${fileId}`);
  
  if (!response.ok) {
    const errorMessage = await parseErrorResponse(response);
    throw new Error(errorMessage);
  }
  
  return response.blob();
}

/**
 * Send a chat message (non-streaming).
 * @param {string} sessionId - Session ID
 * @param {string} message - Chat message
 * @returns {Promise<Object>} Response data
 */
export async function sendMessage(sessionId, message) {
  const response = await fetch(`${API_BASE}/chat/${sessionId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, stream: false }),
  });
  
  if (!response.ok) {
    const errorMessage = await parseErrorResponse(response);
    throw new Error(errorMessage);
  }
  
  return response.json();
}

/**
 * Get chat history.
 * @param {string} sessionId - Session ID
 * @returns {Promise<Array>} Chat messages
 */
export async function getChatHistory(sessionId) {
  const response = await fetch(`${API_BASE}/chat/${sessionId}/history`);

  if (!response.ok) {
    const errorMessage = await parseErrorResponse(response);
    throw new Error(errorMessage);
  }

  return response.json();
}

/**
 * Generate an automatic analyst brief for a session.
 * @param {string} sessionId - Session ID
 * @returns {Promise<Object>} Assistant message
 */
export async function generateBrief(sessionId) {
  const response = await fetch(`${API_BASE}/chat/${sessionId}/brief`, {
    method: 'POST',
  });

  if (!response.ok) {
    const errorMessage = await parseErrorResponse(response);
    throw new Error(errorMessage);
  }

  return response.json();
}

/**
 * List available reports.
 * @param {string} sessionId - Session ID
 * @returns {Promise<Object>} Reports list
 */
export async function listReports(sessionId) {
  const response = await fetch(`${API_BASE}/chat/${sessionId}/reports`);

  if (!response.ok) {
    const errorMessage = await parseErrorResponse(response);
    throw new Error(errorMessage);
  }

  return response.json();
}

/**
 * Extract basename from a sandbox-relative report path.
 * @param {string} src - Path or filename from agent markdown
 * @returns {string}
 */
export function reportBasename(src) {
  if (!src) return '';
  const withoutQuery = src.split('?')[0];
  return withoutQuery.replace(/^outputs\//, '').split('/').pop();
}

/**
 * Build a report download or inline preview URL.
 * @param {string} sessionId
 * @param {string} fileName
 * @param {{ inline?: boolean }} options
 * @returns {string}
 */
export function getReportDownloadUrl(sessionId, fileName, { inline = false } = {}) {
  const encoded = encodeURIComponent(fileName);
  return inline
    ? `${API_BASE}/chat/${sessionId}/reports/${encoded}?inline=1`
    : `${API_BASE}/chat/${sessionId}/reports/${encoded}`;
}

/**
 * Resolve API-relative report paths from the backend.
 * @param {string} path - e.g. /chat/{id}/reports/file.pdf
 * @returns {string}
 */
export function apiReportPath(path) {
  if (!path) return path;
  if (path.startsWith('http') || path.startsWith('/api/')) {
    return path;
  }
  return `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`;
}

/**
 * Harvest workspace files.
 * @param {string} sessionId - Session ID
 * @returns {Promise<Object>} Harvest result
 */
export async function harvestWorkspace(sessionId) {
  const response = await fetch(`${API_BASE}/chat/${sessionId}/harvest`, {
    method: 'POST',
  });

  if (!response.ok) {
    const errorMessage = await parseErrorResponse(response);
    throw new Error(errorMessage);
  }

  return response.json();
}
