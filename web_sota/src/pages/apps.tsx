import { ExternalLink, Grid3X3, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import API_BASE from "@/lib/api";

interface Ship {
  name: string;
  port: number;
  status: string;
  category: string;
}

interface FleetData {
  ships: Ship[];
  summary: { total: number; running: number };
}

export function Apps() {
  const [data, setData] = useState<FleetData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API_BASE}/api/fleet/overview`)
      .then((r) => r.json())
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20" data-testid="apps-page">
        <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
      </div>
    );
  }

  const ships = data?.ships ?? [];

  return (
    <div className="space-y-6" data-testid="apps-page">
      <div className="flex items-center gap-3">
        <Grid3X3 className="h-6 w-6 text-blue-400" />
        <h1 className="text-2xl font-bold text-slate-100">Fleet Apps</h1>
        {data && (
          <span className="rounded-md bg-slate-800 px-2 py-0.5 text-xs text-slate-400">
            {data.summary.running}/{data.summary.total} online
          </span>
        )}
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {ships.map((ship) => (
          <Card key={ship.name} className="border-slate-800 bg-slate-900/50 transition-colors hover:border-slate-700">
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-semibold text-slate-200">
                  {ship.name}
                </CardTitle>
                <a
                  href={`http://127.0.0.1:${ship.port}/health`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="rounded p-1 text-slate-500 hover:text-slate-300 transition-colors"
                >
                  <ExternalLink className="h-4 w-4" />
                </a>
              </div>
            </CardHeader>
            <CardContent>
              <div className="flex items-center gap-3 text-sm">
                <div
                  className={`h-2 w-2 rounded-full ${
                    ship.status === "running" ? "bg-emerald-500" : "bg-slate-600"
                  }`}
                />
                <span className="text-slate-400">{ship.category}</span>
                <span className="ml-auto text-xs text-slate-500">:{ship.port}</span>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
