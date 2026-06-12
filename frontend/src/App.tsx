import { VoicePanel } from "./components/VoicePanel";
import { CalendarView } from "./components/CalendarView";
import { TaskList } from "./components/TaskList";
import { AuthStatus } from "./components/AuthStatus";
import "./App.css";

function App() {
  return (
    <div className="app">
      <header className="app-header">
        <h1>Scheduling Agent</h1>
        <AuthStatus />
      </header>

      <main className="app-main">
        <aside className="app-sidebar">
          <CalendarView />
          <TaskList />
        </aside>

        <section className="app-chat">
          <VoicePanel />
        </section>
      </main>
    </div>
  );
}

export default App;
