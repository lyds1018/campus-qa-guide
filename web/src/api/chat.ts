import { get, getToken, http, post } from "./http";
import type { Me, SessionBrief, StoredMessage, TurnResult } from "./types";

export type StreamHandlers = {
  session?: (d: { conversation_id: string; turn: number }) => void;
  stage?: (d: { stage: string; mode?: string; segments?: number }) => void;
  delta?: (d: { text: string }) => void;
  answer?: (d: TurnResult) => void;
  notice?: (d: { level: string; text: string }) => void;
  error?: (d: { message: string }) => void;
  done?: (d: { conversation_id: string; turn: number; latency_ms: number; trace_id: string }) => void;
};

export function me(): Promise<Me> {
  return get<Me>("/chat/me");
}

export function sessions(limit = 20): Promise<SessionBrief[]> {
  return get<SessionBrief[]>(`/chat/sessions?limit=${limit}`);
}

export function history(conversationId: string): Promise<StoredMessage[]> {
  return get<StoredMessage[]>(`/chat/sessions/${conversationId}`);
}

/**
 * POST + fetch 读流（不用 EventSource：问句在 body 里，也不希望浏览器自动重连重复提问）。
 * 按 `\n\n` 切帧，忽略 `: ping` 注释帧。
 */
export async function streamChat(
  body: { question: string; conversation_id?: string | null; audience?: string },
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Demo-Token": getToken(),
    },
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const data = await response.json();
      detail = data?.detail ?? detail;
    } catch {
      /* 非 JSON 错误体，保留状态码 */
    }
    throw { status: response.status, detail } as { status: number; detail: string };
  }
  if (!response.body) throw { status: 0, detail: "浏览器不支持流式响应" };

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let cut = buffer.indexOf("\n\n");
    while (cut >= 0) {
      const frame = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      dispatch(frame, handlers);
      cut = buffer.indexOf("\n\n");
    }
  }
}

function dispatch(frame: string, handlers: StreamHandlers) {
  if (!frame.trim() || frame.startsWith(":")) return; // 心跳注释帧
  let event = "message";
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (!dataLines.length) return;
  let payload: unknown;
  try {
    payload = JSON.parse(dataLines.join("\n"));
  } catch {
    return;
  }
  const handler = handlers[event as keyof StreamHandlers] as ((d: unknown) => void) | undefined;
  handler?.(payload);
}

export async function exportChecklist(payload: {
  title: string;
  question: string;
  items: { kind: string; text: string; checked: boolean }[];
}): Promise<Blob> {
  const response = await http.post("/chat/export", payload, { responseType: "blob" });
  return response as unknown as Blob;
}

export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

/** 非流式一轮，评测/回放用；页面主路径走 streamChat。 */
export function askOnce(body: {
  question: string;
  conversation_id?: string | null;
}): Promise<TurnResult> {
  return post<TurnResult>("/chat/turn", body);
}
