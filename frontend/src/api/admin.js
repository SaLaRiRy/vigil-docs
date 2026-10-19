import axios from 'axios';

const api = axios.create({
  baseURL: '/api/admin',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
});

// Request interceptor - add admin token
api.interceptors.request.use(
  config => {
    const token = localStorage.getItem('adminToken');
    if (token) {
      config.headers['Authorization'] = `Bearer ${token}`;
    }
    return config;
  },
  error => Promise.reject(error)
);

// Response interceptor
api.interceptors.response.use(
  response => {
    if (response.data.code === 200) {
      return response.data;
    }
    return Promise.reject(new Error(response.data.message || 'Request failed'));
  },
  error => {
    // Unauthorized - clear token and redirect to login
    if (error.response?.status === 401) {
      localStorage.removeItem('adminToken');
      localStorage.removeItem('adminInfo');
      window.location.href = '/admin/login';
    }
    return Promise.reject(error);
  }
);

export const adminAuthAPI = {
  login: (username, password) => {
    const params = new URLSearchParams();
    params.append('username', username);
    params.append('password', password);
    return api.post('/login', params, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
    });
  }
};

export const userManagementAPI = {
  listUsers: (page = 1, size = 10) =>
    api.get(`/users?page=${page}&size=${size}`),
  updateUserStatus: (userId, status) =>
    api.post(`/users/${userId}/status`, null, {
        params: { status }
    })
};

export const knowledgeManagementAPI = {
  upload: (file, categoryId) => {
    const formData = new FormData();
    formData.append('file', file);
    if (categoryId) {
      formData.append('categoryId', categoryId);
    }
    return api.post('/knowledge/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    });
  },
  list: (categoryId) =>
    api.get(`/knowledge/list${categoryId ? `?categoryId=${categoryId}` : ''}`),
  delete: (id) => api.delete(`/knowledge/${id}`),
  retryParse: (id, filePath) =>
    api.post('/knowledge/retry-parse', { id, filePath }),
};

export const qaLogAPI = {
  list: (page = 1, size = 10) =>
    api.get(`/logs?page=${page}&size=${size}`),
};

export const approvalAPI = {
  listPending: () => api.get('/approvals/pending'),
  get: (approvalId) => api.get(`/approvals/${approvalId}`),
  audit: (approvalId) => api.get(`/approvals/${approvalId}/audit`),
  decide: (approvalId, decision, comment = '') =>
    api.post(`/approvals/${approvalId}/decision`, { decision, comment }),
  stream: async (onApproval, onError) => {
    const token = localStorage.getItem('adminToken');
    const controller = new AbortController();
    try {
      const response = await fetch('/api/admin/approvals/stream', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        signal: controller.signal
      });
      if (!response.ok || !response.body) {
        throw new Error(`Approval stream failed with ${response.status}`);
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split('\n\n');
        buffer = events.pop() || '';
        events.forEach(event => {
          const eventName = event.split('\n').find(line => line.startsWith('event:'))?.slice(6).trim();
          const dataLine = event.split('\n').find(line => line.startsWith('data:'));
          if (!dataLine) return;
          try {
            const data = JSON.parse(dataLine.slice(5).trim());
            if (eventName === 'approval.pending' || data.approvalId) onApproval(data);
          } catch (error) {
            console.error('Failed to parse approval SSE event', error);
          }
        });
      }
    } catch (error) {
      if (error.name !== 'AbortError' && onError) onError(error);
    }
    return () => controller.abort();
  }
};

export default api;
