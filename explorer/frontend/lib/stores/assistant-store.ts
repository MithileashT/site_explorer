import { create } from "zustand";
import { persist, createJSONStorage, devtools } from "zustand/middleware";

interface Message {
  role: "user" | "assistant" | "system";
  content: string;
  result?: unknown;
}

interface AssistantState {
  messages: Message[];
  input: string;

  setMessages: (m: Message[]) => void;
  addMessage: (m: Message) => void;
  updateMessage: (index: number, m: Partial<Message>) => void;
  setInput: (i: string) => void;
  resetAssistant: () => void;
}

const WELCOME: Message = {
  role: "system",
  content:
    "👋 **Welcome to the AMR AI Assistant.**\n\nDescribe an incident or ask me to investigate something. I'll use real-time FAISS similarity search + LLM analysis to diagnose issues, rank causes, and suggest solutions.",
};

const initialState = {
  messages: [WELCOME] as Message[],
  input: "",
};

export const useAssistantStore = create<AssistantState>()(
  devtools(
    persist(
      (set) => ({
        ...initialState,
        setMessages: (m) => set({ messages: m }),
        addMessage: (m) =>
          set((state) => ({ messages: [...state.messages, m] })),
        updateMessage: (index, partial) =>
          set((state) => ({
            messages: state.messages.map((msg, i) =>
              i === index ? { ...msg, ...partial } : msg
            ),
          })),
        setInput: (i) => set({ input: i }),
        resetAssistant: () => set(initialState),
      }),
      {
        name: "amr-assistant-state",
        version: 1,
        storage: createJSONStorage(() => sessionStorage),
      }
    ),
    { name: "AssistantStore", enabled: process.env.NODE_ENV === "development" }
  )
);
