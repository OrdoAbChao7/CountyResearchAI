interface Props {
  jobId: string;
  brief: string;
  reportPath: string;
}

export function BriefView({ jobId, brief, reportPath }: Props) {
  function download() {
    const blob = new Blob([brief], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${jobId}-brief.md`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="brief-view">
      <div className="brief-actions">
        <button type="button" onClick={download} disabled={!brief}>
          下载决策简报
        </button>
        {reportPath ? (
          <a
            href={`/api/v1/research/tasks/${jobId}/report`}
            target="_blank"
            rel="noreferrer"
          >
            打开完整报告
          </a>
        ) : null}
      </div>
      {brief ? (
        <pre className="brief">{brief}</pre>
      ) : (
        <p className="muted">简报尚未生成。</p>
      )}
    </div>
  );
}
