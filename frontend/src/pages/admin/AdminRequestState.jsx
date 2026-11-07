export function AdminRequestError({ message, onRetry }) {
  return (
    <div className="admin-request-state error" role="alert">
      <strong>{message}</strong>
      <span>请检查服务状态后重试。</span>
      {onRetry && (
        <button type="button" className="btn btn-primary" onClick={onRetry}>
          重试
        </button>
      )}
    </div>
  );
}

export function AdminEmptyState({ message }) {
  return <div className="admin-request-state empty">{message}</div>;
}
