// Esempio di Dashboard Web per Zylch AI
// Framework: React
// API: http://localhost:8000

import React, { useState, useEffect } from 'react';

const API_URL = 'http://localhost:8000';

function ZylchDashboard() {
  const [gaps, setGaps] = useState(null);
  const [loading, setLoading] = useState(false);
  const [userInput, setUserInput] = useState('');
  const [draft, setDraft] = useState(null);

  // Load daily tasks on mount
  useEffect(() => {
    loadGaps();
  }, []);

  // Load gaps from API
  async function loadGaps() {
    setLoading(true);
    try {
      const response = await fetch(`${API_URL}/api/gaps/summary`);
      const data = await response.json();
      setGaps(data);
    } catch (error) {
      console.error('Failed to load gaps:', error);
    } finally {
      setLoading(false);
    }
  }

  // Sync emails (morning workflow)
  async function syncEmails() {
    setLoading(true);
    try {
      const response = await fetch(`${API_URL}/api/sync/full`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ days_back: 30 })
      });
      const result = await response.json();

      alert(`✅ Sync complete!\nNew: ${result.email_sync?.new_threads || 0}\nUpdated: ${result.email_sync?.updated_threads || 0}`);

      // Reload gaps after sync
      loadGaps();
    } catch (error) {
      alert('❌ Sync failed: ' + error.message);
    } finally {
      setLoading(false);
    }
  }

  // Process natural language with skills
  async function processInput() {
    if (!userInput.trim()) return;

    setLoading(true);
    try {
      const response = await fetch(`${API_URL}/api/skills/process`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_input: userInput,
          user_id: 'mario',
          conversation_history: []
        })
      });
      const result = await response.json();

      if (result.success && result.execution.data) {
        setDraft(result.execution.data);
      } else {
        alert('❌ Failed: ' + (result.execution.error || 'Unknown error'));
      }
    } catch (error) {
      alert('❌ Error: ' + error.message);
    } finally {
      setLoading(false);
    }
  }

  // Approve draft and store pattern
  async function approveDraft() {
    if (!draft) return;

    try {
      await fetch(`${API_URL}/api/patterns/store`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          skill: 'draft_composer',
          intent: userInput,
          context: { draft_approved: true },
          action: { tone: 'formal' },
          outcome: 'User approved and sent',
          user_id: 'mario'
        })
      });

      alert('✅ Draft approved! Pattern learned.');
      setDraft(null);
      setUserInput('');
    } catch (error) {
      alert('❌ Failed to store pattern: ' + error.message);
    }
  }

  return (
    <div style={{ padding: '20px', maxWidth: '1200px', margin: '0 auto' }}>
      <h1>🌟 Zylch AI Dashboard</h1>

      {/* Sync Button */}
      <div style={{ marginBottom: '20px' }}>
        <button
          onClick={syncEmails}
          disabled={loading}
          style={{ padding: '10px 20px', fontSize: '16px' }}
        >
          {loading ? '⏳ Syncing...' : '🔄 Sync Now'}
        </button>
      </div>

      {/* Daily Tasks */}
      {gaps && gaps.has_data && (
        <div style={{ marginBottom: '30px' }}>
          <h2>📋 Your Tasks Today ({gaps.total_tasks})</h2>

          {/* Email Tasks */}
          {gaps.email_tasks.count > 0 && (
            <div style={{ marginBottom: '20px' }}>
              <h3>📧 Email Tasks ({gaps.email_tasks.count})</h3>
              {gaps.email_tasks.top_5.map((task, i) => (
                <div key={i} style={{
                  padding: '10px',
                  border: '1px solid #ddd',
                  marginBottom: '10px',
                  borderRadius: '5px'
                }}>
                  <strong>{task.contact_name}</strong>
                  <br />
                  <small>{task.contact_email}</small>
                  <br />
                  📝 {task.task_description}
                </div>
              ))}
            </div>
          )}

          {/* Meeting Follow-ups */}
          {gaps.meeting_tasks.count > 0 && (
            <div style={{ marginBottom: '20px' }}>
              <h3>📅 Meeting Follow-ups ({gaps.meeting_tasks.count})</h3>
              {gaps.meeting_tasks.top_5.map((task, i) => (
                <div key={i} style={{
                  padding: '10px',
                  border: '1px solid #ddd',
                  marginBottom: '10px',
                  borderRadius: '5px'
                }}>
                  <strong>{task.contact_name}</strong>
                  <br />
                  {task.meeting_summary} ({task.days_ago} days ago)
                  <br />
                  ⚠️ No follow-up email sent yet
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* AI Assistant Input */}
      <div style={{ marginBottom: '30px' }}>
        <h2>🤖 AI Assistant</h2>
        <input
          type="text"
          value={userInput}
          onChange={(e) => setUserInput(e.target.value)}
          onKeyPress={(e) => e.key === 'Enter' && processInput()}
          placeholder="Draft a reminder email to Luisa..."
          style={{
            width: '100%',
            padding: '10px',
            fontSize: '16px',
            marginBottom: '10px'
          }}
          disabled={loading}
        />
        <button
          onClick={processInput}
          disabled={loading || !userInput.trim()}
          style={{ padding: '10px 20px', fontSize: '16px' }}
        >
          {loading ? '⏳ Processing...' : '✨ Generate'}
        </button>
      </div>

      {/* Draft Preview */}
      {draft && (
        <div style={{
          padding: '20px',
          border: '2px solid #4CAF50',
          borderRadius: '10px',
          backgroundColor: '#f9f9f9'
        }}>
          <h3>📧 Generated Draft</h3>
          <p><strong>Subject:</strong> {draft.subject}</p>
          <hr />
          <pre style={{
            whiteSpace: 'pre-wrap',
            fontFamily: 'inherit',
            fontSize: '14px'
          }}>
            {draft.draft}
          </pre>
          <hr />
          <button
            onClick={approveDraft}
            style={{
              padding: '10px 20px',
              fontSize: '16px',
              backgroundColor: '#4CAF50',
              color: 'white',
              border: 'none',
              borderRadius: '5px',
              cursor: 'pointer',
              marginRight: '10px'
            }}
          >
            ✅ Approve & Learn
          </button>
          <button
            onClick={() => setDraft(null)}
            style={{
              padding: '10px 20px',
              fontSize: '16px',
              backgroundColor: '#f44336',
              color: 'white',
              border: 'none',
              borderRadius: '5px',
              cursor: 'pointer'
            }}
          >
            ❌ Discard
          </button>
        </div>
      )}
    </div>
  );
}

export default ZylchDashboard;
