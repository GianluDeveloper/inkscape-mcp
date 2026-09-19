import { Activity, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import API_BASE from "@/lib/api";

export function Status() {
  const [data, setData] = useState<unknown>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback((signal?: AbortSignal) => {
    return fetch(`${API_BASE}/api/health`, { signal })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json() as Promise<unknown>;
      })
      .then((result) => {
        if (signal?.aborted) return;
        setData(result);
        setError(null);
      })
      .catch((error: unknown) => {
        if (signal?.aborted) return;
        setData(null);
        setError(error instanceof Error ? error.message : "Request failed");
      })
      .finally(() => {
        if (!signal?.aborted) setLoading(false);
      });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  return (
    <div className="space-y-6" data-testid="status-page">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-white">
            Server status
          </h2>
          <p className="text-slate-300">
            <code className="text-slate-300">GET /api/health</code> — Inkscape
            CLI, optional Ollama, API keys (no secrets shown).
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            setLoading(true);
            setError(null);
            void load();
          }}
          disabled={loading}
          className="border-slate-800 text-slate-300"
        >
          <RefreshCw
            className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`}
          />
          Refresh
        </Button>
      </div>

      <Card className="border-slate-800 bg-slate-950/50">
        <CardHeader className="flex flex-row items-center gap-2">
          <Activity className="h-5 w-5 text-emerald-500" />
          <CardTitle className="text-white">Health JSON</CardTitle>
        </CardHeader>
        <CardContent>
          {error ? (
            <p className="text-yellow-400">{error}</p>
          ) : (
            <pre className="max-h-[70vh] overflow-auto rounded-lg border border-slate-800 bg-slate-900 p-4 text-xs text-slate-200">
              {loading && !data ? "Loading…" : JSON.stringify(data, null, 2)}
            </pre>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
