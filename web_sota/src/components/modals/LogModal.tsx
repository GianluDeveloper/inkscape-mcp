import * as Dialog from "@radix-ui/react-dialog";
import { ScrollText, X } from "lucide-react";
import { useEffect, useState } from "react";
import API_BASE from "@/lib/api";

interface Props {
  open: boolean;
  onClose: () => void;
}

export function LogModal({ open, onClose }: Props) {
  const [logs, setLogs] = useState<string>("Loading...");

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    fetch(`${API_BASE}/api/logs`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return JSON.stringify(await response.json(), null, 2);
      })
      .then((result) => {
        if (!controller.signal.aborted) setLogs(result);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setLogs(String(error));
      });
    return () => controller.abort();
  }, [open]);

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(v) => {
        if (!v) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 max-h-[85vh] w-[90vw] max-w-3xl -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border border-slate-800 bg-slate-950 p-6 shadow-xl data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95">
          <Dialog.Title className="flex items-center gap-2 text-lg font-semibold text-slate-100">
            <ScrollText className="h-5 w-5 text-amber-500" />
            Server Logs
          </Dialog.Title>

          <Dialog.Close className="absolute right-4 top-4 rounded-md p-1 text-slate-300 hover:bg-slate-800 hover:text-white">
            <X className="h-4 w-4" />
          </Dialog.Close>

          <div className="mt-4">
            <pre className="max-h-[60vh] overflow-auto rounded-lg border border-slate-800 bg-slate-900 p-3 font-mono text-xs text-slate-300">
              {logs}
            </pre>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
