import { useCallback, useEffect, useState } from "react";
import { ActiveLlmCard } from "@/components/llm/ActiveLlmCard";
import { LlmOnboarding } from "@/components/llm/LlmOnboarding";
import { LlmProviderCards } from "@/components/llm/LlmProviderCards";
import {
  fetchLlmSettings,
  fetchProviders,
  loadSelection,
  type ProviderInfo,
} from "@/lib/llm";

export function AiSettings() {
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [probing, setProbing] = useState(true);
  const [selected, setSelected] = useState("ollama");

  const refreshProviders = useCallback(async () => {
    try {
      const pv = await fetchProviders();
      setProviders(pv.providers);
    } catch {
      /* keep previous list */
    }
  }, []);

  useEffect(() => {
    (async () => {
      await refreshProviders();
      const prev = loadSelection();
      if (prev.provider) setSelected(prev.provider);
      try {
        const s = await fetchLlmSettings();
        if (s.provider) setSelected(s.provider);
      } catch {
        /* backend truth unavailable: local mirror stands */
      }
      setProbing(false);
    })();
  }, [refreshProviders]);

  async function handleCardsChanged() {
    await refreshProviders();
  }

  return (
    <div className="space-y-6" data-testid="ai-settings-page">
      <div>
        <h2 className="text-2xl font-bold tracking-tight text-white">
          AI Settings
        </h2>
        <p className="text-slate-300">
          Local and cloud LLM providers used by Chat and agent tools.
        </p>
      </div>
      <LlmOnboarding mode="full" />
      <ActiveLlmCard />
      <LlmProviderCards
        providers={providers}
        probing={probing}
        selected={selected}
        onChanged={handleCardsChanged}
      />
    </div>
  );
}
