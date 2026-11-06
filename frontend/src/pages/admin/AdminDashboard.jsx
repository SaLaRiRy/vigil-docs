import { useCallback, useState, useEffect } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { systemHealthAPI } from '../../api/admin';
import './AdminDashboard.css';

function AdminHealthBanner({ health, error, loading, onRetry }) {
  if (loading) {
    return (
      <div className="system-health-banner healthy" role="status">
        <div>
          <strong>正在获取系统健康状态</strong>
          <span>索引和文档处理状态检查中…</span>
        </div>
      </div>
    );
  }
  const vectorStatus = health?.vectorIndex?.status;
  const consumerStatus = health?.documentConsumer?.status;
  const degraded =
    error ||
    (vectorStatus && !['HEALTHY', 'EMPTY'].includes(vectorStatus)) ||
    (consumerStatus && consumerStatus !== 'HEALTHY');
  const className = degraded ? 'system-health-banner degraded' : 'system-health-banner healthy';

  return (
    <div className={className} role={degraded ? 'alert' : 'status'}>
      <div>
        <strong>{degraded ? '系统需要检查' : '系统运行正常'}</strong>
        <span>
          {error ||
            `索引：${vectorStatus || '未知'} · Consumer：${consumerStatus || '未知'}${
              health?.documentConsumer
                ? ` · 队列 ${health.documentConsumer.queueDepth ?? 0} · Consumer ${health.documentConsumer.consumerCount ?? 0} · PENDING ${health.documentConsumer.pendingCount ?? 0} · 处理中 ${health.documentConsumer.processingCount ?? 0} · 滞留 ${health.documentConsumer.stalePendingCount ?? 0} · 最大尝试 ${health.documentConsumer.maxProcessingAttempts ?? 0}`
                : ''
            }`}
        </span>
        {(health?.vectorIndex?.message || health?.documentConsumer?.message) && (
          <span>{health.vectorIndex?.message || health.documentConsumer?.message}</span>
        )}
        {health?.vectorIndex?.indexedDocumentIds?.length > 0 && (
          <span>
            已索引文档：
            {health.vectorIndex.indexedDocumentIds.slice(0, 20).join(', ')}
            {health.vectorIndex.indexedDocumentIds.length > 20
              ? ` 等 ${health.vectorIndex.indexedDocumentIds.length} 个`
              : ''}
          </span>
        )}
      </div>
      <button type="button" className="btn btn-default" onClick={onRetry}>
        刷新状态
      </button>
    </div>
  );
}

export default function AdminDashboard() {
  const navigate = useNavigate();
  const location = useLocation();
  const [adminInfo, setAdminInfo] = useState(null);
  const [activeMenu, setActiveMenu] = useState('users');
  const [systemHealth, setSystemHealth] = useState(null);
  const [healthError, setHealthError] = useState(null);
  const [healthLoading, setHealthLoading] = useState(true);

  const loadSystemHealth = useCallback(async () => {
    setHealthLoading(true);
    setHealthError(null);
    try {
      const response = await systemHealthAPI.get();
      setSystemHealth(response.data);
    } catch {
      setHealthError('无法获取系统健康状态');
    } finally {
      setHealthLoading(false);
    }
  }, []);

  useEffect(() => {
    document.title = 'VigilDocs - 管理后台';
    return () => {
      document.title = 'VigilDocs';
    };
  }, []);

  useEffect(() => {
    const info = localStorage.getItem('adminInfo');
    if (!info) {
      navigate('/admin/login');
      return;
    }
    setAdminInfo(JSON.parse(info));

    const path = location.pathname;
    if (path.includes('/approvals')) setActiveMenu('approvals');
    else if (path.includes('/dashboard')) setActiveMenu('dashboard');
    else if (path.includes('/users')) setActiveMenu('users');
    else if (path.includes('/knowledge')) setActiveMenu('knowledge');
    else if (path.includes('/logs')) setActiveMenu('logs');
    else if (path.includes('/agent-runs')) setActiveMenu('agent-runs');
    else if (path.includes('/inspection')) setActiveMenu('inspection');
    else if (path.includes('/reports')) setActiveMenu('reports');
    else if (path.includes('/chat')) setActiveMenu('chat');
  }, [navigate, location.pathname]);

  useEffect(() => {
    loadSystemHealth();
    const timer = window.setInterval(loadSystemHealth, 30000);
    return () => window.clearInterval(timer);
  }, [loadSystemHealth]);

  const handleLogout = () => {
    localStorage.removeItem('adminToken');
    localStorage.removeItem('adminInfo');
    navigate('/admin/login');
  };

  const menuItems = [
    { id: 'approvals', label: '待审批操作', icon: '🛡️', path: '/admin/approvals' },
    { id: 'chat', label: '管理助手', icon: '⚙️', path: '/admin/chat' },
    { id: 'dashboard', label: '仪表盘', icon: '📊', path: '/admin/dashboard' },
    { id: 'users', label: '用户管理', icon: '👥', path: '/admin/users' },
    { id: 'knowledge', label: '知识库管理', icon: '📚', path: '/admin/knowledge' },
    { id: 'logs', label: '问答日志', icon: '📝', path: '/admin/logs' },
    { id: 'agent-runs', label: 'Agent执行记录', icon: '🔄', path: '/admin/agent-runs' },
    { id: 'inspection', label: '知识巡检', icon: '🔍', path: '/admin/inspection' },
    { id: 'reports', label: '自动报表', icon: '📈', path: '/admin/reports' },
  ];

  const handleMenuClick = (path) => {
    navigate(path);
  };

  return (
    <div className="admin-layout">
      <div className="admin-sidebar">
        <div className="sidebar-header">
          <h2>🛡️ VigilDocs</h2>
        </div>

        <nav className="sidebar-nav">
          {menuItems.map((item) => (
            <div
              key={item.id}
              className={`nav-item ${activeMenu === item.id ? 'active' : ''}`}
              onClick={() => handleMenuClick(item.path)}
            >
              <span className="nav-icon">{item.icon}</span>
              <span className="nav-label">{item.label}</span>
            </div>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="admin-info">
            <div className="admin-name">{adminInfo?.username}</div>
            <div className="admin-role">{adminInfo?.role}</div>
          </div>
          <button className="btn btn-danger logout-btn" onClick={handleLogout}>
            退出登录
          </button>
        </div>
      </div>

      <div className="admin-main">
        <AdminHealthBanner
          health={systemHealth}
          error={healthError}
          loading={healthLoading}
          onRetry={loadSystemHealth}
        />
        <Outlet />
      </div>
    </div>
  );
}
