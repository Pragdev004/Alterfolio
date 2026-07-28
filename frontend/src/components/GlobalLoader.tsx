import { useLoading } from "../hooks/useLoading";

export function GlobalLoader() {
  const { isLoading } = useLoading();

  if (!isLoading) {
    return null;
  }

  return (
    <div className="global-loader" role="status" aria-live="polite">
      <div className="global-loader-bar" />
    </div>
  );
}
