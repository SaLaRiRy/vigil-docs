import { useCallback, useEffect, useState } from 'react';
import { approvalAPI } from '../../api/admin';
import './ApprovalCenter.css';

export default function ApprovalCenter() {
  const [approvals, setApprovals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState('');
  const [lastDecision, setLastDecision] = useState(null);

  const loadApprovals = useCallback(async () => {
    try {
      const response = await approvalAPI.listPending();
      setApprovals(response.data || []);
      setError('');
    } catch (requestError) {
      setError(requestError.message || '审批列表加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadApprovals();
    let active = true;
    let reconnectTimer;
    let closeStream;

    const connect = async () => {
      closeStream = await approvalAPI.stream(
        () => loadApprovals(),
        streamError => {
          setError(streamError.message || '实时通知断开，正在从 MySQL 恢复');
          if (active) reconnectTimer = window.setTimeout(connect, 3000);
        }
      );
      if (active && !reconnectTimer) {
        reconnectTimer = window.setTimeout(connect, 3000);
      }
    };

    connect();
    return () => {
      active = false;
      window.clearTimeout(reconnectTimer);
      if (closeStream) closeStream();
    };
  }, [loadApprovals]);

  const decide = async (approval, decision) => {
    const defaultComment = decision === 'REJECT' ? 'Deletion request rejected' : '';
    const comment = window.prompt(
      decision === 'APPROVE' ? 'Optional approval comment' : 'Optional rejection reason',
      defaultComment
    );
    if (comment === null) return;

    setSubmitting(`${approval.id}:${decision}`);
    setError('');
    try {
      const response = await approvalAPI.decide(approval.id, decision, comment);
      setLastDecision(response.data);
      await loadApprovals();
    } catch (requestError) {
      setError(requestError.message || '审批提交失败');
    } finally {
      setSubmitting('');
    }
  };

  return (
    <div className="approval-center">
      <div className="page-header">
        <div>
          <h1>待审批操作</h1>
          <p>审批状态以 MySQL 为准；SSE 仅用于提醒新请求。</p>
        </div>
        <button className="btn btn-default" onClick={loadApprovals}>刷新</button>
      </div>

      {error && <div className="approval-error">{error}</div>}
      {lastDecision && (
        <div className="approval-result">
          {lastDecision.approvalId}：{lastDecision.status}
          {lastDecision.idempotentReplay ? '（重复提交已安全忽略）' : ''}
        </div>
      )}

      {loading ? (
        <div className="admin-card">加载中...</div>
      ) : approvals.length === 0 ? (
        <div className="admin-card">当前没有待审批请求。</div>
      ) : (
        <div className="approval-list">
          {approvals.map(approval => (
            <article className="approval-card" key={approval.id}>
              <div className="approval-card-header">
                <div>
                  <div className="approval-doc">{approval.documentName}</div>
                  <div className="approval-meta">文档 #{approval.documentId} · {approval.toolName}</div>
                </div>
                <span className="approval-badge">PENDING</span>
              </div>

              <dl className="approval-details">
                <div><dt>请求人</dt><dd>{approval.requesterId}</dd></div>
                <div><dt>风险</dt><dd>{approval.riskReason}</dd></div>
                <div><dt>runId</dt><dd><code>{approval.runId}</code></dd></div>
                <div><dt>traceId</dt><dd><code>{approval.traceId}</code></dd></div>
                <div>
                  <dt>过期时间</dt>
                  <dd>{approval.expiresAt ? new Date(approval.expiresAt).toLocaleString() : '-'}</dd>
                </div>
              </dl>

              <div className="approval-actions">
                <button
                  className="btn btn-danger"
                  disabled={Boolean(submitting)}
                  onClick={() => decide(approval, 'REJECT')}
                >
                  {submitting === `${approval.id}:REJECT` ? '提交中...' : '拒绝'}
                </button>
                <button
                  className="btn btn-primary"
                  disabled={Boolean(submitting)}
                  onClick={() => decide(approval, 'APPROVE')}
                >
                  {submitting === `${approval.id}:APPROVE` ? '提交中...' : '批准删除'}
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
