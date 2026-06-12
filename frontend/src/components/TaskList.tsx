import { useTasks } from "../hooks/useTasks";
import { ListTodo, RefreshCw } from "lucide-react";

export function TaskList() {
  const { data: tasks, isLoading, refetch, isFetching } = useTasks();

  return (
    <div className="task-list">
      <div className="task-header">
        <div className="task-header-left">
          <ListTodo size={18} />
          <h3>Tasks</h3>
        </div>
        <button
          className="btn-icon"
          onClick={() => refetch()}
          disabled={isFetching}
          title="Refresh"
        >
          <RefreshCw size={14} className={isFetching ? "spin" : ""} />
        </button>
      </div>

      <div className="task-items">
        {isLoading ? (
          <div className="task-loading">Loading...</div>
        ) : tasks && tasks.length > 0 ? (
          tasks.map((task) => (
            <div key={task.id} className="task-card">
              <div className="task-title">{task.title}</div>
              {task.notes && <div className="task-notes">{task.notes}</div>}
              {task.due_date && task.due_date !== "No due date" && (
                <div className="task-due">Due: {task.due_date}</div>
              )}
            </div>
          ))
        ) : (
          <div className="task-empty">No tasks.</div>
        )}
      </div>
    </div>
  );
}
