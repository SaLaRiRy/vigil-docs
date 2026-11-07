import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import Dashboard from './Dashboard';
import AdminDashboard from './AdminDashboard';
import KnowledgeManagement from './KnowledgeManagement';
import UserManagement from './UserManagement';

const getDashboardStats = vi.fn();
const listUsers = vi.fn();
const listDocuments = vi.fn();
const getSystemHealth = vi.fn();

vi.mock('../../api/dashboard', () => ({
  getDashboardStats: (...args) => getDashboardStats(...args),
}));

vi.mock('../../api/admin', () => ({
  userManagementAPI: {
    listUsers: (...args) => listUsers(...args),
    updateUserStatus: vi.fn(),
  },
  knowledgeManagementAPI: {
    list: (...args) => listDocuments(...args),
    upload: vi.fn(),
    delete: vi.fn(),
    retryParse: vi.fn(),
  },
  systemHealthAPI: {
    get: (...args) => getSystemHealth(...args),
  },
}));

describe('admin request states', () => {
  afterEach(() => {
    cleanup();
    localStorage.clear();
    vi.useRealTimers();
  });

  beforeEach(() => {
    getDashboardStats.mockReset();
    listUsers.mockReset();
    listDocuments.mockReset();
    getSystemHealth.mockReset();
  });

  it('shows a retryable dashboard error instead of an empty dashboard', async () => {
    getDashboardStats.mockRejectedValue(new Error('offline'));

    render(<Dashboard />);

    expect(await screen.findByText('加载仪表盘失败')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument();
  });

  it('shows a retryable dashboard error for an unsuccessful business response', async () => {
    getDashboardStats.mockResolvedValue({ code: 500, data: null });

    render(<Dashboard />);

    expect(await screen.findByText('加载仪表盘失败')).toBeInTheDocument();
    expect(screen.queryByText('暂无数据')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument();
  });

  it('shows a retryable user-list error instead of zero users', async () => {
    listUsers.mockRejectedValue(new Error('offline'));

    render(<UserManagement />);

    expect(await screen.findByText('加载用户列表失败')).toBeInTheDocument();
    expect(screen.queryByText('共 0 个用户')).not.toBeInTheDocument();
  });

  it('does not present a zero user count while the first request is in flight', async () => {
    let resolveRequest;
    listUsers.mockReturnValue(new Promise((resolve) => {
      resolveRequest = resolve;
    }));

    render(<UserManagement />);

    expect(screen.getByText('加载中...')).toBeInTheDocument();
    expect(screen.queryByText('共 0 个用户')).not.toBeInTheDocument();

    await act(async () => {
      resolveRequest({ data: { records: [], total: 0 } });
    });
  });

  it('retries a failed document request and then renders its empty state', async () => {
    listDocuments
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ data: [] });

    render(
      <MemoryRouter>
        <KnowledgeManagement />
      </MemoryRouter>,
    );

    expect(await screen.findByText('加载文档列表失败')).toBeInTheDocument();
    expect(screen.queryByText('共 0 个文档')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '重试' }));

    await waitFor(() => {
      expect(screen.getByText('共 0 个文档')).toBeInTheDocument();
      expect(screen.getByText('暂无文档，请先上传')).toBeInTheDocument();
    });
  });

  it('shows a non-blocking health banner when system status cannot be loaded', async () => {
    localStorage.setItem('adminInfo', JSON.stringify({ username: 'admin', role: 'ADMIN' }));
    getSystemHealth.mockRejectedValue(new Error('offline'));

    render(
      <MemoryRouter initialEntries={['/admin/dashboard']}>
        <Routes>
          <Route path="/admin" element={<AdminDashboard />}>
            <Route path="dashboard" element={<div>dashboard content</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText('无法获取系统健康状态')).toBeInTheDocument();
    expect(screen.getByText('dashboard content')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '刷新状态' })).toBeInTheDocument();
  });

  it('polls while a visible document is pending and stops at a terminal state', async () => {
    vi.useFakeTimers();
    listDocuments
      .mockResolvedValueOnce({ data: [{ id: 1, docName: '待处理.txt', status: 'PENDING' }] })
      .mockResolvedValueOnce({ data: [{ id: 1, docName: '待处理.txt', status: 'COMPLETED' }] });

    render(
      <MemoryRouter>
        <KnowledgeManagement />
      </MemoryRouter>,
    );

    await act(async () => {
      await Promise.resolve();
    });
    expect(listDocuments).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(2000);
      await Promise.resolve();
    });
    expect(listDocuments).toHaveBeenCalledTimes(2);
    expect(screen.getByText('已完成')).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(4000);
      await Promise.resolve();
    });
    expect(listDocuments).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
  });

  it('does not overlap document polling while one request is pending', async () => {
    vi.useFakeTimers();
    let resolveDocuments;
    listDocuments.mockReturnValue(new Promise(resolve => {
      resolveDocuments = resolve;
    }));

    render(
      <MemoryRouter>
        <KnowledgeManagement />
      </MemoryRouter>,
    );

    await act(async () => {
      await Promise.resolve();
    });
    expect(listDocuments).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(2000);
      await Promise.resolve();
    });
    expect(listDocuments).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveDocuments({ data: [] });
      await Promise.resolve();
    });
    expect(screen.getByText('暂无文档，请先上传')).toBeInTheDocument();
  });

  it('does not overlap health checks while one is pending', async () => {
    localStorage.setItem('adminInfo', JSON.stringify({ username: 'admin', role: 'ADMIN' }));
    vi.useFakeTimers();
    let resolveHealth;
    getSystemHealth.mockReturnValue(new Promise(resolve => {
      resolveHealth = resolve;
    }));

    render(
      <MemoryRouter initialEntries={['/admin/dashboard']}>
        <Routes>
          <Route path="/admin" element={<AdminDashboard />}>
            <Route path="dashboard" element={<div>dashboard content</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    await act(async () => {
      await Promise.resolve();
    });
    expect(getSystemHealth).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(95000);
      await Promise.resolve();
    });
    expect(getSystemHealth).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveHealth({
        data: {
          vectorIndex: { status: 'HEALTHY' },
          documentConsumer: { status: 'HEALTHY' },
        },
      });
      await Promise.resolve();
    });

    await act(async () => {
      vi.advanceTimersByTime(30000);
      await Promise.resolve();
    });
    expect(getSystemHealth).toHaveBeenCalledTimes(2);
  });

});
