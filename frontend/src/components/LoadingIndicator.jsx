export default function LoadingIndicator() {
  return (
    <div className="flex w-full justify-start">
      <div className="flex max-w-[80%] items-center gap-2 rounded-3xl bg-gray-200 px-4 py-3">
        <div className="spinner" />
        <span className="text-gray-600">Thinking...</span>
      </div>
    </div>
  );
}
