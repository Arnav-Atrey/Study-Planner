import { useCallback, useEffect, useRef, useState } from 'react';
import { Navigate } from 'react-router-dom';
import { api } from '../api/client';
import LoadingIndicator from '../components/LoadingIndicator';
import MessageBubble from '../components/MessageBubble';
import { useAuth } from '../context/AuthContext';

const WELCOME_MESSAGE =
  "Hello! I'm your AI Study Planner. What topic would you like to study today?";

export default function Chat() {
  const { user, loading, logout } = useAuth();
  const [conversations, setConversations] = useState([]);
  const [currentConversationId, setCurrentConversationId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [initializing, setInitializing] = useState(true);
  const chatEndRef = useRef(null);

  const scrollToBottom = useCallback(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  const loadConversations = useCallback(async () => {
    const data = await api.listConversations();
    return data.conversations || [];
  }, []);

  const loadHistory = useCallback(async (conversationId) => {
    if (!conversationId) {
      setMessages([]);
      return;
    }
    const data = await api.getChatHistory(conversationId);
    setMessages(data.messages || []);
  }, []);

  const selectConversation = useCallback(
    async (id) => {
      setCurrentConversationId(id);
      const convos = await loadConversations();
      setConversations(convos);
      await loadHistory(id);
    },
    [loadConversations, loadHistory],
  );

  useEffect(() => {
    if (!user) return;

    async function init() {
      setInitializing(true);
      try {
        let convos = await loadConversations();
        if (convos.length === 0) {
          const conv = await api.createConversation('New chat');
          convos = await loadConversations();
          setCurrentConversationId(conv.id);
          setMessages([]);
        } else {
          setCurrentConversationId(convos[0].id);
          await loadHistory(convos[0].id);
        }
        setConversations(convos);
      } finally {
        setInitializing(false);
      }
    }

    init();
  }, [user, loadConversations, loadHistory]);

  useEffect(() => {
    scrollToBottom();
  }, [messages, sending, scrollToBottom]);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-gray-600">
        Loading…
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  async function handleNewChat() {
    const conv = await api.createConversation('New chat');
    const convos = await loadConversations();
    setConversations(convos);
    setCurrentConversationId(conv.id);
    setMessages([]);
  }

  async function handleSend() {
    const message = input.trim();
    if (!message || sending) return;

    setInput('');
    setSending(true);
    setMessages((prev) => [...prev, { role: 'user', content: message }]);

    try {
      const data = await api.sendMessage(message, currentConversationId);
      if (data.conversation_id) {
        setCurrentConversationId(data.conversation_id);
      }
      setMessages((prev) => [...prev, { role: 'assistant', content: data.response }]);
      const convos = await loadConversations();
      setConversations(convos);
    } catch (err) {
      const detail = err.data?.detail || err.message || 'Something went wrong.';
      setMessages((prev) => [...prev, { role: 'assistant', content: `Error: ${detail}` }]);
    } finally {
      setSending(false);
    }
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleSend();
    }
  }

  const showWelcome = messages.length === 0;

  return (
    <div className="flex h-screen bg-gray-100">
      <aside className="flex w-60 min-w-60 flex-col border-r border-gray-200 bg-white p-3">
        <button
          type="button"
          onClick={handleNewChat}
          className="mb-2 w-full rounded-lg border border-gray-200 px-3 py-2 text-left font-medium text-blue-500 hover:bg-gray-100"
        >
          + New chat
        </button>
        <nav className="flex-1 overflow-y-auto" aria-label="Conversations">
          {conversations.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => selectConversation(c.id)}
              className={`mb-0.5 block w-full truncate rounded-md px-3 py-2 text-left text-sm ${
                c.id === currentConversationId
                  ? 'bg-blue-100 text-blue-700'
                  : 'text-gray-700 hover:bg-gray-100'
              }`}
            >
              {c.title || 'New chat'}
            </button>
          ))}
        </nav>
      </aside>

      <div className="mx-auto flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between bg-white p-4 shadow-sm">
          <span className="text-xl font-bold text-gray-800">AI Study Planner</span>
          <div className="flex items-center gap-3">
            <span className="text-sm text-gray-600">{user.username}</span>
            <button
              type="button"
              onClick={logout}
              className="rounded-lg bg-gray-200 px-4 py-2 text-sm text-gray-700 hover:bg-gray-300"
            >
              Log out
            </button>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto p-4">
          {initializing ? (
            <div className="flex h-full items-center justify-center text-gray-500">
              Loading chat…
            </div>
          ) : (
            <div className="mx-auto flex max-w-3xl flex-col gap-4">
              {showWelcome && <MessageBubble role="assistant" content={WELCOME_MESSAGE} />}
              {messages.map((m, i) => (
                <MessageBubble key={`${m.role}-${i}`} role={m.role} content={m.content} />
              ))}
              {sending && <LoadingIndicator />}
              <div ref={chatEndRef} />
            </div>
          )}
        </main>

        <footer className="bg-white p-4">
          <div className="mx-auto flex max-w-3xl items-center">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={sending || initializing}
              placeholder="Type your message..."
              className="flex-1 rounded-full border-2 border-gray-300 p-3 focus:border-blue-500 focus:outline-none disabled:opacity-60"
            />
            <button
              type="button"
              onClick={handleSend}
              disabled={sending || initializing}
              className="ml-4 rounded-full bg-blue-500 px-6 py-3 font-semibold text-white transition-colors hover:bg-blue-600 disabled:opacity-60"
            >
              Send
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}
