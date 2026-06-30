/**
 * Hermes API client — server-side fetch with error handling.
 * Used by React Server Components.
 */

const HERMES_URL = process.env.NEXT_PUBLIC_HERMES_URL ?? "http://hermes:8000";

export async function hermesApi<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${HERMES_URL}${path}`;
  const res = await fetch(url, {
    ...options,
    next: { revalidate: 30 },
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });

  if (!res.ok) {
    throw new Error(`Hermes API error: ${res.status} ${res.statusText} — ${url}`);
  }

  return res.json() as Promise<T>;
}
