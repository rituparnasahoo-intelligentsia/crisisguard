// frontend/src/api.ts
// Use host.docker.internal so the Docker container can reach your Windows FastAPI server
const API_BASE = "http://127.0.0.1:8000";

export async function fetchState() {
  const res = await fetch(`${API_BASE}/state`);
  if (!res.ok) throw new Error("Failed to fetch state");
  return res.json();
}

export async function approveProposal(proposalId: string, reviewer: string = "React Admin") {
  const res = await fetch(`${API_BASE}/proposals/${proposalId}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reviewer, reason: "Approved via Dashboard" })
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || "Failed to approve");
  }
  return res.json();
}