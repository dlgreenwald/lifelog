import { useState, useEffect } from 'react';
import { api } from '../api/client';
import type { Decision } from '../types';

export default function DecisionsList() {
  const [decisions, setDecisions] = useState<Decision[]>([]);

  useEffect(() => {
    api.getDecisions().then((data: { decisions: Decision[] }) => {
      setDecisions(data.decisions);
    });
  }, []);

  return (
    <div className="decisions-list">
      <h2>Recent Decisions</h2>
      {decisions.length === 0 ? (
        <p>No decisions found</p>
      ) : (
        <ul>
          {decisions.map((decision, i) => (
            <li key={i}>
              <strong>{decision.decision}</strong>
              <span> - {decision.made_by}</span>
              {decision.context && <p className="context">{decision.context}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
