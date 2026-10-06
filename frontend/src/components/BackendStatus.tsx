import { useHealth } from "../hooks/useHealth";

export function BackendStatus() {
  const health = useHealth();

  if (health.isPending) {
    return <p className="status status--pending">Checking backend…</p>;
  }

  if (health.isError) {
    return <p className="status status--error">Backend unavailable</p>;
  }

  return <p className="status status--success">Backend connected</p>;
}

