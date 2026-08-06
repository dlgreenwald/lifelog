import { BrowserRouter, Routes, Route, Link } from 'react-router-dom';
import Calendar from './components/Calendar';
import RecordingDetail from './components/RecordingDetail';
import TodoList from './components/TodoList';
import DecisionsList from './components/DecisionsList';
import SpeakerLabel from './components/SpeakerLabel';

export default function App() {
  return (
    <BrowserRouter>
      <div className="app">
        <header>
          <h1>LifeLog</h1>
          <nav>
            <Link to="/">Calendar</Link>
            <Link to="/todos">TODOs</Link>
            <Link to="/decisions">Decisions</Link>
            <Link to="/speakers">Speakers</Link>
          </nav>
        </header>
        <main>
          <Routes>
            <Route path="/" element={<Calendar />} />
            <Route path="/recording/:id" element={<RecordingDetail />} />
            <Route path="/todos" element={<TodoList />} />
            <Route path="/decisions" element={<DecisionsList />} />
            <Route path="/speakers" element={<SpeakerLabel />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
