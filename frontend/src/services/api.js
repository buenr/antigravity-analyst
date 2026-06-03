/**
 * API service for communicating with the backend.
 */

const API_BASE = '/api';
const SESSION_ID_STORAGE_KEY = 'antigravity_session_id';
const SESSION_TOKEN_STORAGE_KEY = 'antigravity_session_token';
const SESSION_HISTORY_KEY = 'antigravity_session_history';

export function getStoredSessionId() {
  return localStorage.getItem(SESSION_ID_STORAGE_KEY);
}

export function getStoredSessionToken() {
  return localStorage.getItem(SESSION_TOKEN_STORAGE_KEY);
}

export function storeSessionCredentials(session) {
  localStorage.setItem(SESSION_ID_STORAGE_KEY, session.session_id);
  localStorage.setItem(SESSION_TOKEN_STORAGE_KEY, session.session_token);
  addToSessionHistory(session);
}

export function clearSessionCredentials() {
  localStorage.removeItem(SESSION_ID_STORAGE_KEY);
  localStorage.removeItem(SESSION_TOKEN_STORAGE_KEY);
}

export function getSessionHistory() {
  try {
    const history = localStorage.getItem(SESSION_HISTORY_KEY);
    return history ? JSON.parse(history) : [];
  } catch {
    return [];
  }
}

export function addToSessionHistory(session) {
  const history = getSessionHistory();
  const existingIndex = history.findIndex(s => s.session_id === session.session_id);
  
  const sessionEntry = {
    session_id: session.session_id,
    session_token: session.session_token,
    tenant_id: session.tenant_id,
    created_at: session.created_at || new Date().toISOString(),
    last_accessed: new Date().toISOString(),
  };
  
  if (existingIndex >= 0) {
    history[existingIndex] = { ...history[existingIndex], ...sessionEntry };
  } else {
    history.unshift(sessionEntry);
  }
  
  // Keep only the last 20 sessions
  const trimmedHistory = history.slice(0, 20);
  localStorage.setItem(SESSION_HISTORY_KEY, JSON.stringify(trimmedHistory));
  return trimmedHistory;
}

export function removeFromSessionHistory(sessionId) {
  const history = getSessionHistory();
  const filtered = history.filter(s => s.session_id !== sessionId);
  localStorage.setItem(SESSION_HISTORY_KEY, JSON.stringify(filtered));
  return filtered;
}

export function clearSessionHistory() {
  localStorage.removeItem(SESSION_HISTORY_KEY);
}

export function setActiveSession(session) {
  localStorage.setItem(SESSION_ID_STORAGE_KEY, session.session_id);
  localStorage.setItem(SESSION_TOKEN_STORAGE_KEY, session.session_token);
  addToSessionHistory(session);
}

function authHeaders(headers = {}) {
  const token = getStoredSessionToken();
  return token ? { ...headers, 'X-Session-Token': token } : headers;
}

function appendSessionToken(url) {
  const token = getStoredSessionToken();
  if (!token || url.includes('session_token=')) return url;
  const separator = url.includes('?') ? '&' : '?';
  return `${url}${separator}session_token=${encodeURIComponent(token)}`;
}

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
 * List sessions for the current session token.
 * @returns {Promise<Array>} List of sessions
 */
export async function listSessions() {
  const response = await fetch(`${API_BASE}/sessions/`, {
    headers: authHeaders(),
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
  const response = await fetch(`${API_BASE}/sessions/${sessionId}`, {
    headers: authHeaders(),
  });
  
  if (!response.ok) {
    const errorMessage = await parseErrorResponse(response);
    throw new Error(errorMessage);
  }
  
  return response.json();
}

/**
 * Delete a session and its persisted files.
 * @param {string} sessionId - Session ID
 * @returns {Promise<void>}
 */
export async function deleteSession(sessionId) {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}`, {
    method: 'DELETE',
    headers: authHeaders(),
  });

  if (!response.ok) {
    const errorMessage = await parseErrorResponse(response);
    throw new Error(errorMessage);
  }
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
    headers: authHeaders(),
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
  const response = await fetch(`${API_BASE}/files/${sessionId}`, {
    headers: authHeaders(),
  });
  
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
  const response = await fetch(`${API_BASE}/files/download/${fileId}`, {
    headers: authHeaders(),
  });
  
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
 * @param {Array<{data:string,mime_type:string}>} images - Optional inline images
 * @returns {Promise<Object>} Response data
 */
export async function sendMessage(sessionId, message, images = []) {
  const response = await fetch(`${API_BASE}/chat/${sessionId}`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ message, stream: false, images }),
  });

  if (!response.ok) {
    const errorMessage = await parseErrorResponse(response);
    throw new Error(errorMessage);
  }

  return response.json();
}

/**
 * Read a File object and return base64 (without data: prefix) + mime type.
 * @param {File} file
 * @returns {Promise<{data: string, mime_type: string}>}
 */
export function fileToImageInput(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result || '';
      const commaIdx = result.indexOf(',');
      const data = commaIdx >= 0 ? result.slice(commaIdx + 1) : result;
      resolve({ data, mime_type: file.type || 'image/png' });
    };
    reader.onerror = () => reject(reader.error || new Error('Failed to read image'));
    reader.readAsDataURL(file);
  });
}

/**
 * Get chat history.
 * @param {string} sessionId - Session ID
 * @returns {Promise<Array>} Chat messages
 */
export async function getChatHistory(sessionId) {
  const response = await fetch(`${API_BASE}/chat/${sessionId}/history`, {
    headers: authHeaders(),
  });

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
    headers: authHeaders(),
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
  const response = await fetch(`${API_BASE}/chat/${sessionId}/reports`, {
    headers: authHeaders(),
  });

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
  const baseUrl = `${API_BASE}/chat/${sessionId}/reports/${encoded}`;
  return appendSessionToken(inline ? `${baseUrl}?inline=1` : baseUrl);
}

/**
 * Resolve API-relative report paths from the backend.
 * @param {string} path - e.g. /chat/{id}/reports/file.pdf
 * @returns {string}
 */
export function apiReportPath(path) {
  if (!path) return path;
  if (path.startsWith('http') || path.startsWith('/api/')) {
    return appendSessionToken(path);
  }
  return appendSessionToken(`${API_BASE}${path.startsWith('/') ? path : `/${path}`}`);
}

/**
 * Harvest workspace files.
 * @param {string} sessionId - Session ID
 * @returns {Promise<Object>} Harvest result
 */
export async function harvestWorkspace(sessionId) {
  const response = await fetch(`${API_BASE}/chat/${sessionId}/harvest`, {
    method: 'POST',
    headers: authHeaders(),
  });

  if (!response.ok) {
    const errorMessage = await parseErrorResponse(response);
    throw new Error(errorMessage);
  }

  return response.json();
}
