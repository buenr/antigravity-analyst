/**
 * API service for communicating with the backend.
 */

const API_BASE = '/api';

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
    const error = await response.json();
    throw new Error(error.detail || 'Failed to create session');
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
    throw new Error('Failed to get session');
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
    const error = await response.json();
    throw new Error(error.detail || 'Failed to upload file');
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
    throw new Error('Failed to list files');
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
    throw new Error('Failed to download file');
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
    const error = await response.json();
    throw new Error(error.detail || 'Failed to send message');
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
    throw new Error('Failed to get chat history');
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
    const error = await response.json();
    throw new Error(error.detail || 'Failed to generate analyst brief');
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
    throw new Error('Failed to list reports');
  }
  
  return response.json();
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
    throw new Error('Failed to harvest workspace');
  }
  
  return response.json();
}
