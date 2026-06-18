import { marked } from 'marked';

export default function MessageBubble({ role, content }) {
  const isUser = role === 'user';

  return (
    <div className={`flex w-full ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[80%] rounded-3xl px-4 py-3 ${
          isUser ? 'bg-blue-500 text-white' : 'bg-gray-200 text-gray-700'
        }`}
      >
        {isUser ? (
          <div className="message-content break-words">{content}</div>
        ) : (
          <div
            className="message-content break-words"
            dangerouslySetInnerHTML={{ __html: marked.parse(content || '') }}
          />
        )}
      </div>
    </div>
  );
}
