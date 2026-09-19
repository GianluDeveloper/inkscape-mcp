/**
 * Active LLM card (SETTINGS_LLM.md rules enforced): no-auto-pick, switch-on-
 * save, kick-out, VRAM + residents readouts. Self-contained - fetches its own
 * providers/settings/telemetry. Vendored from mcp-central-docs/templates/llm/.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  fetchGpus,
  fetchLoaded,
  fetchModels,
  fetchProviders,
  type GpuInfo,
  type LoadedModel,
  loadSelection,
  type ProviderInfo,
  saveLlmSettings,
  saveSelection,
  unloadLlm,
} from "@/lib/llm";

function gb(mb: number): string {
  return `${(mb / 1024).toFixed(1)} GB`;
}

export function ActiveLlmCard() {
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [selected, setSelected] = useState("ollama");
  const [model, setModel] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [modelsSource, setModelsSource] = useState("");
  const [endpoints, setEndpoints] = useState<Record<string, string>>({});
  const [probing, setProbing] = useState(true);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [kicking, setKicking] = useState(false);
  const [gpus, setGpus] = useState<GpuInfo[]>([]);
  const [loaded, setLoaded] = useState<LoadedModel[]>([]);

  const reloadModels = useCallback(async (id: string) => {
    try {
      const m = await fetchModels(id);
      setModels(m.models);
      setModelsSource(m.source);
      // RULE: never auto-pick. Keep a still-valid choice, else empty.
      setModel((cur) => (cur && m.models.includes(cur) ? cur : ""));
    } catch {
      setModels([]);
      setModelsSource("none");
    }
  }, []);

  const refreshLoaded = useCallback(
    async (
      providerId: string,
      kind: string | undefined,
      endpoint: string | undefined,
    ) => {
      if (kind !== "local" || providerId !== "ollama") {
        setLoaded([]);
        return;
      }
      try {
        const d = await fetchLoaded(providerId, endpoint);
        setLoaded(d.models);
      } catch {
        setLoaded([]);
      }
    },
    [],
  );

  // Eviction frees CUDA asynchronously: re-read now + twice delayed so a
  // single instant read can't freeze a stale number on screen.
  const timersRef = useRef<number[]>([]);
  useEffect(() => {
    const timers = timersRef.current;
    return () => {
      for (const t of timers) clearTimeout(t);
      timers.length = 0;
    };
  }, []);

  const refreshTelemetry = useCallback(
    (
      providerId: string,
      kind: string | undefined,
      endpoint: string | undefined,
    ) => {
      const tick = async () => {
        try {
          setGpus(await fetchGpus());
        } catch {
          /* keep previous readout */
        }
        await refreshLoaded(providerId, kind, endpoint);
      };
      void tick();
      timersRef.current.push(
        window.setTimeout(() => void tick(), 2000),
        window.setTimeout(() => void tick(), 5000),
      );
    },
    [refreshLoaded],
  );

  useEffect(() => {
    (async () => {
      const [providersRes, settingsRes, gpusRes] = await Promise.allSettled([
        fetchProviders(),
        apiGet<{ provider?: string; endpoint?: string; model?: string }>(
          "/api/settings/llm",
        ),
        fetchGpus(),
      ]);
      if (providersRes.status === "fulfilled") {
        const list = providersRes.value.providers;
        setProviders(list);
        const eps: Record<string, string> = {};
        for (const p of list) eps[p.id] = p.base_url;
        let selId = "ollama";
        if (settingsRes.status === "fulfilled") {
          const s = settingsRes.value;
          if (s.provider) {
            selId = s.provider;
          } else {
            const prev = loadSelection();
            if (prev.provider) selId = prev.provider;
          }
          if (s.endpoint && s.provider) eps[s.provider] = s.endpoint;
          if (s.model) setModel(s.model);
        } else {
          const prev = loadSelection();
          if (prev.provider) selId = prev.provider;
          if (prev.model) setModel(prev.model);
        }
        setSelected(selId);
        setEndpoints(eps);
        void refreshLoaded(
          selId,
          list.find((p) => p.id === selId)?.kind,
          eps[selId],
        );
      }
      if (gpusRes.status === "fulfilled") setGpus(gpusRes.value);
      setProbing(false);
    })();
  }, [refreshLoaded]);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    fetchModels(selected)
      .then((result) => {
        if (cancelled) return;
        setModels(result.models);
        setModelsSource(result.source);
        setModel((current) =>
          current && result.models.includes(current) ? current : "",
        );
      })
      .catch(() => {
        if (cancelled) return;
        setModels([]);
        setModelsSource("none");
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);

  async function chooseProvider(id: string) {
    setSelected(id);
    setSaveMsg(null);
    void refreshLoaded(
      id,
      providers.find((p) => p.id === id)?.kind,
      endpoints[id],
    );
  }

  async function save() {
    setSaveMsg(null);
    try {
      const res = await saveLlmSettings({
        provider: selected,
        endpoint: endpoints[selected],
        model,
      });
      saveSelection(selected, model);
      const pv = await fetchProviders().catch(() => null);
      if (pv) setProviders(pv.providers);
      await reloadModels(selected);
      const bits = ["Saved."];
      const sw = res.switch;
      if (sw && selected === "ollama" && model) {
        if (!sw.engine)
          bits.push("Ollama engine unreachable — start it first.");
        if (sw.evicted.length) bits.push(`Evicted: ${sw.evicted.join(", ")}.`);
        bits.push(
          sw.warmed
            ? `${model} is loaded.`
            : `Warning: ${model} did not warm up.`,
        );
      }
      setSaveMsg(bits.join(" "));
      refreshTelemetry(
        selected,
        providers.find((p) => p.id === selected)?.kind,
        endpoints[selected],
      );
    } catch (e) {
      setSaveMsg(e instanceof Error ? e.message : String(e));
    }
  }

  // Kick every loaded model out of VRAM (loads nothing) and clear the
  // selection everywhere, so nothing silently reloads behind your back.
  async function kickOut() {
    setSaveMsg(null);
    setKicking(true);
    try {
      const res = await unloadLlm({
        provider: selected,
        endpoint: endpoints[selected],
      });
      await saveLlmSettings({
        provider: selected,
        endpoint: endpoints[selected],
        model: "",
      });
      saveSelection(selected, "");
      setModel("");
      const bits = res.evicted.length
        ? [`Kicked out: ${res.evicted.join(", ")}. Selection cleared.`]
        : ["Nothing was loaded. Selection cleared."];
      setSaveMsg(bits.join(" "));
      setLoaded([]);
      refreshTelemetry(
        selected,
        providers.find((p) => p.id === selected)?.kind,
        endpoints[selected],
      );
    } catch (e) {
      setSaveMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setKicking(false);
    }
  }

  const isLocal = providers.find((p) => p.id === selected)?.kind === "local";

  return (
    <Card className="border-slate-800 bg-slate-950/50 p-4 space-y-3">
      <p className="text-xs text-slate-400">Active LLM (used by Chat)</p>
      {probing && (
        <p
          className="text-xs text-slate-400 animate-pulse"
          data-testid="llm-loading"
        >
          Loading providers…
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-xs text-slate-400" htmlFor="llm-provider">
          Provider
        </label>
        <select
          id="llm-provider"
          data-testid="llm-provider-select"
          value={selected}
          disabled={probing}
          onChange={(e) => void chooseProvider(e.target.value)}
          className="rounded border border-slate-700 bg-slate-800 px-2 py-1 text-sm text-slate-200"
        >
          {providers.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label} ({p.kind})
            </option>
          ))}
        </select>
        <label className="text-xs text-slate-400" htmlFor="llm-model">
          Model
        </label>
        {models.length > 0 ? (
          <select
            id="llm-model"
            data-testid="llm-model-select"
            value={model}
            disabled={probing}
            onChange={(e) => setModel(e.target.value)}
            className="rounded border border-slate-700 bg-slate-800 px-2 py-1 text-sm font-mono text-slate-200"
          >
            <option value="">— pick a model —</option>
            {models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        ) : (
          <input
            id="llm-model"
            data-testid="llm-model-select"
            value={model}
            disabled={probing}
            onChange={(e) => setModel(e.target.value)}
            placeholder="model id"
            aria-label="Model name"
            className="rounded border border-slate-700 bg-slate-800 px-2 py-1 text-sm font-mono text-slate-200 w-40"
          />
        )}
        {modelsSource && (
          <span className="text-xs text-slate-500">source: {modelsSource}</span>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-xs text-slate-400" htmlFor="llm-endpoint">
          Endpoint
        </label>
        <input
          id="llm-endpoint"
          data-testid="llm-endpoint"
          value={endpoints[selected] ?? ""}
          disabled={probing}
          onChange={(e) =>
            setEndpoints((eps) => ({ ...eps, [selected]: e.target.value }))
          }
          className="rounded border border-slate-700 bg-slate-800 px-2 py-1 text-sm font-mono text-slate-200 w-64"
        />
        <Button
          size="sm"
          data-testid="settings-llm-save"
          onClick={save}
          disabled={probing}
          className="bg-blue-600 hover:bg-blue-700 text-white"
        >
          Save
        </Button>
        {isLocal && (
          <Button
            size="sm"
            variant="secondary"
            data-testid="settings-llm-kick"
            onClick={kickOut}
            disabled={kicking || probing}
          >
            {kicking ? "Kicking…" : "Kick LLM out"}
          </Button>
        )}
        {saveMsg && <span className="text-xs text-slate-400">{saveMsg}</span>}
      </div>
      {isLocal && (
        <div className="text-xs text-slate-400" data-testid="llm-vram">
          {gpus.length > 0 ? (
            <span>
              VRAM:{" "}
              {gpus.map((g) => (
                <span key={g.index} className="font-mono">
                  GPU{g.index} {gb(g.used_mb)} / {gb(g.total_mb)} used
                  {g.index < gpus.length - 1 ? " · " : ""}
                </span>
              ))}
            </span>
          ) : (
            <span>No GPU telemetry (nvidia-smi unavailable).</span>
          )}
        </div>
      )}
      {isLocal && selected === "ollama" && (
        <div
          className="flex flex-wrap items-center gap-1.5 text-xs text-slate-400"
          data-testid="llm-loaded"
        >
          <span>Loaded:</span>
          {loaded.length > 0 ? (
            loaded.map((m) => (
              <span
                key={m.name}
                className="rounded bg-slate-800/70 px-1.5 py-0.5 font-mono"
              >
                {m.name} · {gb(m.size_vram_mb)}
              </span>
            ))
          ) : (
            <span>None loaded — VRAM free.</span>
          )}
        </div>
      )}
    </Card>
  );
}
