import type { TaskIndexRow } from "../api/types";

interface SidebarProps {
    tasks: TaskIndexRow[];
    selected: string | null;
    onSelect: (task: string) => void;
}

function taskDate(mtime: number): string {
    return new Date(mtime * 1000).toLocaleDateString("zh-TW", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
    });
}

export function Sidebar({ tasks, selected, onSelect }: SidebarProps) {
    return (
        <aside className="sidebar">
            <div className="brand">
                <div className="brand-logo">研</div>
                <div>
                    <div className="brand-name">回測研究工作台</div>
                    <div className="brand-sub">Research Workbench</div>
                </div>
            </div>
            <div className="sidebar-section-title">回測任務</div>
            <nav className="task-list">
                {tasks.map((row) => (
                    <button
                        key={row.task}
                        type="button"
                        title={row.task}
                        className={`task-item${row.task === selected ? " selected" : ""}`}
                        onClick={() => onSelect(row.task)}
                    >
                        <div className="task-item-name">{row.title}</div>
                        <div className="task-item-date">
                            {taskDate(row.mtime)}
                        </div>
                    </button>
                ))}
                {tasks.length === 0 && (
                    <div className="empty-state">尚無任務</div>
                )}
            </nav>
            <div className="sidebar-footer">資料來源：research API（唯讀）</div>
        </aside>
    );
}
