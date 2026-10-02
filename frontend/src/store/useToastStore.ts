import { create } from "zustand";

export type ToastTone = "success" | "error" | "info";

export interface Toast {
  id: number;
  tone: ToastTone;
  message: string;
}

interface ToastState {
  toasts: Toast[];
  show: (message: string, tone?: ToastTone) => void;
  dismiss: (id: number) => void;
}

let counter = 0;

export const useToastStore = create<ToastState>((set, get) => ({
  toasts: [],
  show: (message, tone = "success") => {
    counter += 1;
    const id = counter;
    set({ toasts: [...get().toasts, { id, tone, message }].slice(-4) });
    window.setTimeout(() => get().dismiss(id), tone === "error" ? 8000 : 4000);
  },
  dismiss: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),
}));

export const toast = (message: string, tone?: ToastTone) => useToastStore.getState().show(message, tone);
