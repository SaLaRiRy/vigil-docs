import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { knowledgeAPI } from '../api/index';
import './Knowledge.css';

const terminalStatuses = new Set(['COMPLETED', 'FAILED', 'DELETED']);

const statusLabels = {
  PENDING: { text: '排队中', className: 'pending' },
  PROCESSING: { text: '处理中', className: 'pending' },
  COMPLETED: { text: '已完成', className: 'completed' },
  FAILED: { text: '失败', className: 'failed' },
  WAITING_APPROVAL: { text: '等待审批', className: 'pending' },
  DELETED: { text: '已删除', className: 'failed' }
};

export default function Knowledge() {
  const navigate = useNavigate();
  const userId = localStorage.getItem('userId');
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [selectedFile, setSelectedFile] = useState(null);
  const [message, setMessage] = useState('');

  const loadDocuments = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const response = await knowledgeAPI.list();
      setDocuments(response.data || []);
    } catch (error) {
      console.error('Failed to load documents', error);
      if (!silent) setMessage(error.message || '加载文档失败');
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!userId) {
      navigate('/login');
      return;
    }
    loadDocuments();
  }, [userId, navigate, loadDocuments]);

  useEffect(() => {
    const hasActiveDocument = documents.some(document => !terminalStatuses.has(document.status));
    if (!hasActiveDocument) return undefined;
    const timer = window.setInterval(() => loadDocuments(true), 2000);
    return () => window.clearInterval(timer);
  }, [documents, loadDocuments]);

  const handleUpload = async () => {
    if (!selectedFile) return;
    setUploading(true);
    setMessage('');
    try {
      await knowledgeAPI.upload(selectedFile);
      setSelectedFile(null);
      const input = document.getElementById('file-input');
      if (input) input.value = '';
      await loadDocuments(true);
    } catch (error) {
      setMessage(error.message || '上传失败');
    } finally {
      setUploading(false);
    }
  };

  const handleDeletionRequest = async document => {
    const confirmed = window.confirm(`Request approval to delete “${document.docName}”?`);
    if (!confirmed) return;
    try {
      const response = await knowledgeAPI.requestDeletion(document.id);
      setMessage(response.data?.message || '删除请求已提交，等待管理员审批');
      await loadDocuments(true);
    } catch (error) {
      setMessage(error.message || '删除请求失败');
    }
  };

  const statusBadge = status => {
    const info = statusLabels[status] || { text: status, className: '' };
    return <span className={`status-badge ${info.className}`}>{info.text}</span>;
  };

  return (
    <div className="knowledge-container">
      <div className="knowledge-header">
        <h1>知识库管理</h1>
        <button className="btn btn-default" onClick={() => navigate('/chat')}>
          返回聊天
        </button>
      </div>

      <div className="upload-section card">
        <h3>上传文档</h3>
        <div className="upload-area">
          <input
            id="file-input"
            type="file"
            onChange={event => setSelectedFile(event.target.files[0] || null)}
            accept=".txt,.pdf,.doc,.docx,.md"
          />
          <button
            className="btn btn-primary"
            onClick={handleUpload}
            disabled={!selectedFile || uploading}
          >
            {uploading ? '上传中...' : '上传'}
          </button>
        </div>
        <p className="upload-hint">支持 .txt, .pdf, .doc, .docx, .md 格式</p>
        {message && <p className="upload-hint">{message}</p>}
      </div>

      <div className="document-section card">
        <h3>文档列表</h3>
        {loading ? (
          <div className="loading">加载中...</div>
        ) : documents.length === 0 ? (
          <div className="empty-list">暂无文档，请先上传</div>
        ) : (
          <table className="document-table">
            <thead>
              <tr>
                <th>文档名称</th>
                <th>状态</th>
                <th>上传时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {documents.map(document => (
                <tr key={document.id}>
                  <td className="doc-name">
                    {document.docName}
                    {document.status === 'FAILED' && document.errorMessage && (
                      <div className="document-error">{document.errorMessage}</div>
                    )}
                  </td>
                  <td>{statusBadge(document.status)}</td>
                  <td>{new Date(document.createTime).toLocaleString()}</td>
                  <td>
                    <button
                      className="btn btn-danger btn-sm"
                      disabled={['WAITING_APPROVAL', 'DELETED'].includes(document.status)}
                      onClick={() => handleDeletionRequest(document)}
                    >
                      请求删除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
