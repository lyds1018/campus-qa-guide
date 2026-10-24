<script setup lang="ts">
import { ElMessage } from "element-plus";
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { useRoute } from "vue-router";

import {
  exportChecklist,
  history,
  saveBlob,
  sendFeedback,
  sessions,
  streamChat,
  type FeedbackBody,
} from "../api/chat";
import type { ChecklistItem, EvidenceItem, SessionBrief, TurnResult } from "../api/types";
import AppIcon from "../components/AppIcon.vue";

interface Bubble {
  role: "user" | "assistant";
  text: string;
  result?: TurnResult;
  stage?: string;
  notices: string[];
  error?: string;
  pending?: boolean;
}

const route = useRoute();

const question = ref("");
const streaming = ref(false);
const messages = ref<Bubble[]>([]);
const conversationId = ref<string | null>(null);
const list = ref<SessionBrief[]>([]);
const tab = ref<"evidence" | "checklist">("evidence");
const checked = ref<Record<string, boolean>>({});
const scroller = ref<HTMLElement>();
const sidebarOpen = ref(false);
const contextOpen = ref(false);
const expanded = ref<Set<number>>(new Set());
const stickToBottom = ref(true);
let controller: AbortController | null = null;

const fbDialog = ref(false);
const fbIndex = ref(-1);
const fbSent = ref<Record<number, string>>({});
const fbForm = reactive<{ reason: string; expect: "answer" | "refuse" | "unsure"; note: string }>({
  reason: "incomplete",
  expect: "answer",
  note: "",
});

const REASONS = [
  { value: "wrong_fact", label: "口径或数字有误" },
  { value: "incomplete", label: "回答不完整" },
  { value: "off_topic", label: "答非所问" },
  { value: "outdated", label: "信息已过期" },
  { value: "other", label: "其他问题" },
];

const STARTERS = [
  { label: "证件补办", question: "学生证丢了怎么补办" },
  { label: "学籍服务", question: "成绩单在哪里打印" },
  { label: "校园卡", question: "校园卡丢了去哪儿补" },
  { label: "奖助政策", question: "国家奖学金的奖励标准是多少" },
];

const STAGE_TEXT: Record<string, string> = {
  understand: "正在核对问题",
  route: "正在确认范围",
  fanout: "正在并行查阅",
  retrieve: "正在查找校务资料",
  generate: "正在整理答复",
};

const KIND_LABEL: Record<string, string> = {
  material: "材料",
  step: "步骤",
  condition: "条件",
  notice: "提示",
};

const REFUSAL_LABEL: Record<string, string> = {
  empty_question: "未填写问题",
  too_long: "问题过长",
  out_of_scope: "超出校务范围",
  no_evidence: "未找到可靠依据",
  low_confidence: "依据不足",
  ungrounded: "未通过核对",
};

const lastAnswer = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i -= 1) {
    if (messages.value[i].result) return messages.value[i].result as TurnResult;
  }
  return null;
});

const evidence = computed<EvidenceItem[]>(() => {
  const seen = new Set<number>();
  const out: EvidenceItem[] = [];
  for (const seg of lastAnswer.value?.segments ?? []) {
    for (const item of seg.evidence ?? []) {
      if (seen.has(item.chunk_id)) continue;
      seen.add(item.chunk_id);
      out.push(item);
    }
  }
  return out;
});

const checklist = computed<ChecklistItem[]>(() => lastAnswer.value?.checklist ?? []);

const checkedCount = computed(
  () => checklist.value.filter((item) => checked.value[itemKey(item)]).length,
);

const progress = computed(() =>
  checklist.value.length ? Math.round((checkedCount.value / checklist.value.length) * 100) : 0,
);

const activeTitle = computed(() => {
  if (!conversationId.value) return "新对话";
  return list.value.find((item) => item.id === conversationId.value)?.title || "当前会话";
});

function stageLabel(stage: string): string {
  return STAGE_TEXT[stage] ?? "正在处理";
}

function itemKey(item: ChecklistItem): string {
  return `${item.kind}-${item.ordinal}`;
}

function isChecked(item: ChecklistItem): boolean {
  return checked.value[itemKey(item)] ?? false;
}

function toggle(item: ChecklistItem) {
  checked.value = { ...checked.value, [itemKey(item)]: !isChecked(item) };
}

function isExpanded(chunkId: number): boolean {
  return expanded.value.has(chunkId);
}

function toggleEvidence(chunkId: number) {
  const next = new Set(expanded.value);
  if (next.has(chunkId)) next.delete(chunkId);
  else next.add(chunkId);
  expanded.value = next;
}

function answerState(m: Bubble): string {
  if (!m.result) return "";
  if (m.result.answerable) return "依据原文作答";
  return REFUSAL_LABEL[m.result.refusal_reason ?? ""] ?? "未作答";
}

function formatLatency(ms: number): string {
  if (!ms) return "";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

function formatSessionTime(value: string): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  }
  return date.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
}

function closeDrawers() {
  sidebarOpen.value = false;
  contextOpen.value = false;
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === "Escape") closeDrawers();
}

async function scrollToBottom(force = false) {
  if (!force && !stickToBottom.value) return;
  await nextTick();
  const el = scroller.value;
  if (el) el.scrollTop = el.scrollHeight;
}

function onScroll() {
  const el = scroller.value;
  if (!el) return;
  stickToBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
}

async function refreshSessions() {
  try {
    list.value = await sessions(20);
  } catch {
    /* 侧栏失败不影响对话 */
  }
}

function resetFeedback() {
  fbSent.value = {};
}

function resetAnswerView() {
  tab.value = "evidence";
  expanded.value = new Set();
}

function newChat() {
  controller?.abort();
  conversationId.value = null;
  messages.value = [];
  checked.value = {};
  stickToBottom.value = true;
  resetAnswerView();
  resetFeedback();
  closeDrawers();
}

async function openSession(id: string) {
  if (streaming.value) controller?.abort();
  try {
    const rows = await history(id);
    conversationId.value = id;
    checked.value = {};
    resetAnswerView();
    resetFeedback();
    messages.value = rows.map((row) =>
      row.role === "user"
        ? { role: "user" as const, text: row.content, notices: [] }
        : {
            role: "assistant" as const,
            text: row.content,
            result: row.payload as TurnResult,
            notices: (row.payload as TurnResult)?.notices ?? [],
          },
    );
    closeDrawers();
    stickToBottom.value = true;
    await scrollToBottom(true);
  } catch (e) {
    ElMessage.error((e as { detail?: string }).detail ?? "加载会话失败");
  }
}

function askStarter(text: string) {
  if (streaming.value) return;
  question.value = text;
  void send();
}

async function send() {
  const text = question.value.trim();
  if (!text || streaming.value) return;
  question.value = "";
  messages.value.push({ role: "user", text, notices: [] });
  const bubble = reactive<Bubble>({ role: "assistant", text: "", notices: [], pending: true });
  messages.value.push(bubble);
  streaming.value = true;
  stickToBottom.value = true;
  resetAnswerView();
  await scrollToBottom(true);

  controller = new AbortController();
  const current = controller;

  try {
    await streamChat(
      { question: text, conversation_id: conversationId.value },
      {
        session: (d) => {
          conversationId.value = d.conversation_id;
        },
        stage: (d) => {
          bubble.stage = d.stage;
        },
        delta: (d) => {
          bubble.text += d.text;
          void scrollToBottom();
        },
        answer: (d) => {
          bubble.result = d;
          bubble.text = d.text;
          bubble.notices = d.notices ?? [];
        },
        notice: (d) => {
          bubble.notices.push(d.text);
        },
        error: (d) => {
          bubble.error = d.message;
        },
        done: () => {
          bubble.pending = false;
          bubble.stage = undefined;
        },
      },
      current.signal,
    );
  } catch (e) {
    if (current.signal.aborted) {
      bubble.notices.push("已停止生成，以上为已返回的内容。");
    } else {
      const err = e as { status?: number; detail?: string };
      bubble.error = err.status === 429 ? "请求过于频繁，请稍后再试" : err.detail ?? "请求失败";
    }
  } finally {
    if (controller === current) {
      controller = null;
      streaming.value = false;
    }
    bubble.pending = false;
    bubble.stage = undefined;
    await refreshSessions();
    await scrollToBottom();
  }
}

function stop() {
  controller?.abort();
}

async function doExport() {
  if (!checklist.value.length) {
    ElMessage.info("先问一个办事事项，再导出清单");
    return;
  }
  try {
    const blob = await exportChecklist({
      title: lastAnswer.value?.matter_name || "办事清单",
      question: lastAnswer.value?.question ?? "",
      items: checklist.value.map((item) => ({
        kind: item.kind,
        text: item.text,
        checked: isChecked(item),
      })),
    });
    saveBlob(blob, `${lastAnswer.value?.matter_name || "办事清单"}.csv`);
  } catch (e) {
    ElMessage.error((e as { detail?: string }).detail ?? "导出失败");
  }
}

function fbBase(bubble: Bubble): FeedbackBody | null {
  if (!bubble.result) return null;
  return {
    question: bubble.result.question,
    rating: "up",
    answer_excerpt: bubble.text.slice(0, 200),
    conversation_id: conversationId.value ?? undefined,
    trace_id: bubble.result.trace_id,
  };
}

async function quickFeedback(index: number, bubble: Bubble) {
  if (fbSent.value[index] || !fbBase(bubble)) return;
  try {
    await sendFeedback(fbBase(bubble) as FeedbackBody);
    fbSent.value = { ...fbSent.value, [index]: "已记为有用" };
  } catch (e) {
    ElMessage.error((e as { detail?: string }).detail ?? "反馈失败");
  }
}

function openDown(index: number, bubble: Bubble) {
  if (!fbBase(bubble)) return;
  fbIndex.value = index;
  fbForm.reason = "incomplete";
  fbForm.expect = bubble.result?.answerable ? "answer" : "unsure";
  fbForm.note = "";
  fbDialog.value = true;
}

async function submitDown() {
  const bubble = messages.value[fbIndex.value];
  const base = bubble ? fbBase(bubble) : null;
  if (!base) return;
  try {
    await sendFeedback({
      ...base,
      rating: "down",
      reason: fbForm.reason,
      expect: fbForm.expect,
      note: fbForm.note,
    });
    fbSent.value = { ...fbSent.value, [fbIndex.value]: "已记录，会进入人工复核" };
    fbDialog.value = false;
  } catch (e) {
    ElMessage.error((e as { detail?: string }).detail ?? "反馈失败");
  }
}

onMounted(async () => {
  await refreshSessions();
  const deepLink = route.query.c;
  if (typeof deepLink === "string" && deepLink) await openSession(deepLink);
  window.addEventListener("keydown", onKeydown);
});

onBeforeUnmount(() => {
  controller?.abort();
  window.removeEventListener("keydown", onKeydown);
});
</script>

<template>
  <div class="chat-page">
    <button
      v-if="sidebarOpen || contextOpen"
      type="button"
      class="scrim"
      aria-label="关闭侧栏"
      @click="closeDrawers"
    />

    <aside class="session-rail" :class="{ open: sidebarOpen }">
      <div class="rail-head">
        <span class="rail-label">会话</span>
        <button
          type="button"
          class="icon-button rail-close"
          aria-label="关闭会话栏"
          @click="sidebarOpen = false"
        >
          <AppIcon name="close" />
        </button>
      </div>

      <button type="button" class="new-chat" @click="newChat">
        <AppIcon name="plus" :size="17" />
        <span>新对话</span>
      </button>

      <div class="session-list">
        <button
          v-for="item in list"
          :key="item.id"
          type="button"
          class="session-item"
          :class="{ active: item.id === conversationId }"
          @click="openSession(item.id)"
        >
          <span class="session-title">{{ item.title || "未命名会话" }}</span>
          <span class="session-meta">
            {{ item.turn_count }} 轮
            <i />
            {{ formatSessionTime(item.last_active_at) }}
          </span>
        </button>

        <div v-if="!list.length" class="rail-empty">
          <AppIcon name="history" :size="20" />
          <p>这里会保留你问过的问题</p>
        </div>
      </div>

      <p class="rail-note">会话记录仅保存在当前演示环境。</p>
    </aside>

    <section class="dialog-panel">
      <header class="thread-bar">
        <div class="thread-title">
          <button
            type="button"
            class="icon-button mobile-only"
            aria-label="打开会话栏"
            @click="sidebarOpen = true"
          >
            <AppIcon name="menu" />
          </button>
          <span class="thread-name">{{ activeTitle }}</span>
        </div>
        <button
          type="button"
          class="context-toggle"
          :aria-expanded="contextOpen"
          aria-controls="answer-context"
          @click="contextOpen = true"
        >
          <AppIcon name="book" :size="16" />
          回答依据
          <span class="count-badge">{{ evidence.length }}</span>
        </button>
      </header>

      <div ref="scroller" class="thread-scroller" @scroll.passive="onScroll">
        <div v-if="!messages.length" class="welcome">
          <p class="eyebrow">校园办事 · 服务指南</p>
          <h1 class="welcome-title serif">把问题说清楚，<br />事情就好办。</h1>
          <p class="welcome-lead">
            查询证件补办、奖助政策、学籍与校园服务。回答只使用校内公开资料，
            并附上可核对的原文。
          </p>

          <div class="starter-head">
            <span>可以这样问</span>
            <i />
          </div>
          <div class="starter-grid">
            <button
              v-for="(starter, index) in STARTERS"
              :key="starter.question"
              type="button"
              class="starter"
              @click="askStarter(starter.question)"
            >
              <span class="starter-index">{{ String(index + 1).padStart(2, "0") }}</span>
              <span class="starter-copy">
                <small>{{ starter.label }}</small>
                <strong>{{ starter.question }}</strong>
              </span>
              <AppIcon name="arrow-up-right" :size="16" />
            </button>
          </div>

          <p class="trust-note">
            <AppIcon name="shield" :size="15" />
            没有可靠依据时，系统会直接说明，不猜测、不拼凑。
          </p>
        </div>

        <div v-else class="messages" aria-live="polite">
          <article v-for="(m, i) in messages" :key="i" class="message" :class="m.role">
            <template v-if="m.role === 'user'">
              <div class="user-question">{{ m.text }}</div>
            </template>

            <template v-else>
              <div class="answer-author">
                <span class="author-rule" />
                <span>系统答复</span>
                <span v-if="m.result" class="answer-state">
                  <i :class="{ refused: !m.result.answerable }" />
                  {{ answerState(m) }}
                </span>
              </div>

              <div v-if="m.pending && !m.text" class="pending-line">
                <span class="pending-dots"><i /><i /><i /></span>
                <span>{{ m.stage ? stageLabel(m.stage) : "正在准备答复" }}</span>
              </div>
              <div v-else class="answer-text">{{ m.text }}</div>

              <div v-if="m.error" class="answer-error">
                <AppIcon name="alert" :size="16" />
                <span>{{ m.error }}</span>
              </div>

              <ul v-if="m.notices.length" class="notices">
                <li v-for="(n, k) in m.notices" :key="k">{{ n }}</li>
              </ul>

              <footer v-if="m.result" class="answer-footer">
                <div class="answer-facts">
                  <button
                    v-if="evidence.length"
                    type="button"
                    class="fact-link"
                    @click="tab = 'evidence'; contextOpen = true"
                  >
                    {{ m.result.citations?.length ?? 0 }} 条引用
                  </button>
                  <span v-if="m.result.mode === 'fanout'">已拆分多问</span>
                  <span v-if="m.result.degraded">备用模型</span>
                  <span>{{ formatLatency(m.result.latency_ms) }}</span>
                </div>
                <div class="answer-actions">
                  <span v-if="fbSent[i]" class="fb-done">{{ fbSent[i] }}</span>
                  <template v-else>
                    <button
                      type="button"
                      class="icon-text-button"
                      :aria-label="`第 ${i + 1} 条回答有帮助`"
                      @click="quickFeedback(i, m)"
                    >
                      <AppIcon name="thumb-up" :size="15" />
                      <span>有用</span>
                    </button>
                    <button
                      type="button"
                      class="icon-text-button"
                      :aria-label="`第 ${i + 1} 条回答没有帮助`"
                      @click="openDown(i, m)"
                    >
                      <AppIcon name="thumb-down" :size="15" />
                      <span>没用</span>
                    </button>
                  </template>
                </div>
              </footer>
            </template>
          </article>
        </div>
      </div>

      <div class="composer-wrap">
        <div class="composer">
          <label for="question" class="sr-only">输入校务问题</label>
          <textarea
            id="question"
            v-model="question"
            rows="2"
            maxlength="200"
            placeholder="想问什么？例如：补办学生证需要哪些材料"
            @keydown.enter.exact.prevent="send"
          />
          <div class="composer-foot">
            <div class="composer-note">
              <span>Enter 发送 · Shift + Enter 换行</span>
              <span class="char-count" :class="{ near: question.length > 170 }">
                {{ question.length }}/200
              </span>
            </div>
            <button
              v-if="!streaming"
              type="button"
              class="send-button"
              :disabled="!question.trim()"
              aria-label="发送问题"
              @click="send"
            >
              <AppIcon name="send" :size="18" />
            </button>
            <button v-else type="button" class="send-button stop" aria-label="停止生成" @click="stop">
              <AppIcon name="stop" :size="17" />
            </button>
          </div>
        </div>
        <p class="composer-disclaimer">回答生成后仍建议按原文核对，重要事项以办理窗口口径为准。</p>
      </div>
    </section>

    <aside id="answer-context" class="context-pane" :class="{ open: contextOpen }">
      <div class="context-head">
        <div>
          <p class="eyebrow">资料出处</p>
          <h2>回答依据</h2>
        </div>
        <button
          type="button"
          class="icon-button context-close"
          aria-label="关闭回答依据"
          @click="contextOpen = false"
        >
          <AppIcon name="close" />
        </button>
      </div>

      <div class="context-tabs" role="tablist" aria-label="回答依据分类">
        <button
          type="button"
          role="tab"
          :aria-selected="tab === 'evidence'"
          :class="{ active: tab === 'evidence' }"
          @click="tab = 'evidence'"
        >
          原文 <span>{{ evidence.length }}</span>
        </button>
        <button
          type="button"
          role="tab"
          :aria-selected="tab === 'checklist'"
          :class="{ active: tab === 'checklist' }"
          @click="tab = 'checklist'"
        >
          办事清单 <span>{{ checklist.length }}</span>
        </button>
      </div>

      <div v-if="tab === 'evidence'" class="context-scroll">
        <div v-if="!evidence.length" class="context-empty">
          <AppIcon name="book" :size="24" />
          <p>回答生成后，这里会列出对应的校务原文。</p>
        </div>

        <article
          v-for="item in evidence"
          :key="item.chunk_id"
          class="evidence-card"
          :class="{ expanded: isExpanded(item.chunk_id) }"
        >
          <div class="evidence-head">
            <span class="evidence-ref">{{ String(item.ref).padStart(2, "0") }}</span>
            <div class="evidence-title">
              <h3>{{ item.title }}</h3>
              <p>
                {{ item.section || "正文" }}
                <template v-if="item.page > 1"> · 第 {{ item.page }} 页</template>
              </p>
            </div>
            <span class="evidence-score" :title="`相关度 ${item.score.toFixed(2)}`">
              {{ item.score.toFixed(2) }}
            </span>
          </div>
          <p class="evidence-text">{{ item.content }}</p>
          <button type="button" class="text-link" @click="toggleEvidence(item.chunk_id)">
            {{ isExpanded(item.chunk_id) ? "收起原文" : "展开原文" }}
          </button>
        </article>
      </div>

      <div v-else class="context-scroll">
        <div v-if="!checklist.length" class="context-empty">
          <AppIcon name="check" :size="24" />
          <p>查询办事事项后，会在这里生成可勾选的清单。</p>
        </div>

        <template v-else>
          <div class="checklist-summary">
            <div class="summary-numbers">
              <strong>{{ checkedCount }}</strong>
              <span>/ {{ checklist.length }} 项已准备</span>
            </div>
            <div class="progress-track" :aria-label="`完成 ${progress}%`">
              <span :style="{ width: `${progress}%` }" />
            </div>
            <div class="summary-foot">
              <span>勾选状态会写入导出的文件</span>
              <button type="button" class="text-link export" @click="doExport">
                <AppIcon name="download" :size="14" />
                导出
              </button>
            </div>
          </div>

          <label v-for="item in checklist" :key="itemKey(item)" class="check-row">
            <input type="checkbox" :checked="isChecked(item)" @change="toggle(item)" />
            <span class="check-box" aria-hidden="true">
              <AppIcon name="check" :size="12" />
            </span>
            <span class="check-body">
              <small>{{ KIND_LABEL[item.kind] ?? item.kind }}</small>
              <span :class="{ done: isChecked(item) }">{{ item.text }}</span>
            </span>
          </label>
        </template>
      </div>
    </aside>

    <el-dialog v-model="fbDialog" title="这条回答哪里不对？" width="460px">
      <el-form label-width="72px">
        <el-form-item label="原因">
          <el-select v-model="fbForm.reason" style="width: 100%">
            <el-option v-for="r in REASONS" :key="r.value" :label="r.label" :value="r.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="应该">
          <el-radio-group v-model="fbForm.expect">
            <el-radio value="answer">应该能答</el-radio>
            <el-radio value="refuse">应该拒答</el-radio>
            <el-radio value="unsure">说不清</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="补充">
          <el-input
            v-model="fbForm.note"
            type="textarea"
            :rows="3"
            maxlength="200"
            placeholder="可补充正确口径或缺失内容"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="fbDialog = false">取消</el-button>
        <el-button type="primary" @click="submitDown">提交反馈</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.chat-page {
  display: grid;
  grid-template-columns: 248px minmax(0, 1fr) 364px;
  height: calc(100dvh - var(--header-h));
  overflow: hidden;
  background: var(--surface);
}

.icon-button {
  display: inline-grid;
  width: 34px;
  height: 34px;
  padding: 0;
  place-items: center;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--ink-muted);
  cursor: pointer;
  transition: background-color 160ms ease, color 160ms ease, border-color 160ms ease;
}

.icon-button:hover {
  border-color: var(--line);
  background: var(--surface);
  color: var(--ink);
}

/* 会话栏 */
.session-rail {
  display: flex;
  min-width: 0;
  flex-direction: column;
  padding: 22px 14px 16px;
  border-right: 1px solid var(--line);
  background: var(--paper);
}

.rail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 8px 14px;
}

.rail-label {
  color: var(--ink-muted);
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.14em;
}

.rail-close,
.mobile-only {
  display: none;
}

.new-chat {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  width: 100%;
  min-height: 40px;
  border: 1px solid var(--primary);
  border-radius: 7px;
  background: var(--primary);
  color: #f8f5ed;
  font-size: 13px;
  cursor: pointer;
  transition: background-color 160ms ease;
}

.new-chat:hover {
  background: var(--primary-hover);
}

.session-list {
  flex: 1;
  min-height: 0;
  margin-top: 18px;
  overflow-y: auto;
}

.session-item {
  position: relative;
  display: flex;
  width: 100%;
  flex-direction: column;
  gap: 3px;
  padding: 10px 9px 10px 12px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition: background-color 150ms ease;
}

.session-item::before {
  position: absolute;
  top: 12px;
  bottom: 12px;
  left: 0;
  width: 2px;
  border-radius: 1px;
  background: transparent;
  content: "";
}

.session-item:hover {
  background: var(--surface);
}

.session-item.active {
  background: var(--surface);
}

.session-item.active::before {
  background: var(--primary);
}

.session-title {
  overflow: hidden;
  color: var(--ink-soft);
  font-size: 12.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-item.active .session-title {
  color: var(--ink);
  font-weight: 600;
}

.session-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--ink-faint);
  font-size: 10px;
}

.session-meta i {
  width: 2px;
  height: 2px;
  border-radius: 50%;
  background: currentcolor;
}

.rail-empty {
  padding: 28px 12px;
  color: var(--ink-faint);
  text-align: center;
}

.rail-empty p {
  margin: 8px 0 0;
  font-size: 11px;
}

.rail-note {
  margin: 14px 8px 0;
  padding-top: 12px;
  border-top: 1px solid var(--line);
  color: var(--ink-faint);
  font-size: 10px;
  line-height: 1.6;
}

/* 对话主区 */
.dialog-panel {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  background: var(--surface-raised);
}

.thread-bar {
  display: flex;
  min-height: 58px;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 0 28px;
  border-bottom: 1px solid var(--line);
}

.thread-title {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
}

.thread-name {
  overflow: hidden;
  color: var(--ink-soft);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.context-toggle {
  display: none;
  align-items: center;
  gap: 6px;
  padding: 6px 9px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--ink-soft);
  font-size: 11px;
  cursor: pointer;
}

.count-badge {
  display: grid;
  min-width: 17px;
  height: 17px;
  padding: 0 4px;
  place-items: center;
  border-radius: 9px;
  background: var(--primary-soft);
  color: var(--primary);
  font-family: var(--mono);
  font-size: 9px;
}

.thread-scroller {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  scroll-behavior: smooth;
}

.welcome {
  width: min(760px, 100%);
  margin: 0 auto;
  padding: 8vh 44px 48px;
}

.welcome-title {
  margin: 0;
  color: var(--ink);
  font-size: clamp(34px, 4vw, 48px);
  font-weight: 600;
  line-height: 1.28;
}

.welcome-lead {
  max-width: 540px;
  margin: 20px 0 0;
  color: var(--ink-muted);
  font-size: 13.5px;
  line-height: 1.85;
}

.starter-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 42px 0 12px;
  color: var(--ink-muted);
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.12em;
}

.starter-head i {
  height: 1px;
  flex: 1;
  background: var(--line);
}

.starter-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  border-top: 1px solid var(--line);
}

.starter {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 10px 14px 6px;
  border: 0;
  border-bottom: 1px solid var(--line);
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition: background-color 160ms ease, padding 160ms ease;
}

.starter:nth-child(odd) {
  border-right: 1px solid var(--line);
}

.starter:hover {
  padding-right: 12px;
  padding-left: 8px;
  background: var(--surface);
}

.starter-index {
  width: 20px;
  flex: 0 0 auto;
  color: var(--ink-faint);
  font-family: var(--mono);
  font-size: 10px;
}

.starter-copy {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 2px;
}

.starter-copy small {
  color: var(--ink-faint);
  font-size: 10px;
}

.starter-copy strong {
  color: var(--ink-soft);
  font-size: 13.5px;
  font-weight: 500;
}

.starter > svg {
  color: var(--ink-faint);
  transition: color 160ms ease, transform 160ms ease;
}

.starter:hover > svg {
  color: var(--primary);
  transform: translate(1px, -1px);
}

.trust-note {
  display: flex;
  align-items: center;
  gap: 7px;
  margin: 26px 0 0;
  color: var(--ink-faint);
  font-size: 11px;
  line-height: 1.6;
}

/* 消息 */
.messages {
  width: min(780px, 100%);
  margin: 0 auto;
  padding: 36px 44px 30px;
}

.message {
  margin-bottom: 32px;
}

.message.user {
  display: flex;
  justify-content: flex-end;
}

.user-question {
  max-width: 78%;
  padding: 11px 15px;
  border-radius: 10px 10px 3px;
  background: var(--primary);
  color: #f7f4ed;
  font-size: 13.5px;
  line-height: 1.7;
  white-space: pre-wrap;
}

.message.assistant {
  padding-bottom: 6px;
}

.answer-author {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 11px;
  color: var(--ink-muted);
  font-size: 10.5px;
}

.author-rule {
  width: 14px;
  height: 1px;
  background: var(--primary);
}

.answer-state {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-left: auto;
  color: var(--ink-faint);
}

.answer-state i {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--success);
}

.answer-state i.refused {
  background: var(--warning);
}

.answer-text {
  color: var(--ink);
  font-size: 14.5px;
  line-height: 1.92;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.pending-line {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 4px 0;
  color: var(--ink-muted);
  font-size: 12px;
}

.pending-dots {
  display: flex;
  gap: 3px;
}

.pending-dots i {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--primary);
  animation: breathe 1.2s ease-in-out infinite;
}

.pending-dots i:nth-child(2) {
  animation-delay: 0.15s;
}

.pending-dots i:nth-child(3) {
  animation-delay: 0.3s;
}

@keyframes breathe {
  0%,
  100% {
    opacity: 0.24;
    transform: translateY(0);
  }

  50% {
    opacity: 1;
    transform: translateY(-2px);
  }
}

.notices {
  margin: 14px 0 0;
  padding: 9px 12px;
  border-left: 2px solid var(--warning);
  background: #faf6ee;
  color: var(--ink-muted);
  font-size: 11.5px;
  line-height: 1.7;
  list-style: none;
}

.notices li + li {
  margin-top: 4px;
}

.answer-error {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  margin-top: 12px;
  padding: 9px 11px;
  border: 1px solid #e7d4cf;
  border-radius: 6px;
  background: #fbf3f0;
  color: var(--danger);
  font-size: 12px;
}

.answer-footer {
  display: flex;
  min-height: 34px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 14px;
  padding-top: 9px;
  border-top: 1px solid var(--line);
}

.answer-facts,
.answer-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--ink-faint);
  font-size: 10px;
}

.fact-link {
  padding: 0;
  border: 0;
  border-bottom: 1px solid var(--line-strong);
  background: transparent;
  color: var(--ink-muted);
  font-size: 10px;
  cursor: pointer;
}

.fact-link:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.icon-text-button {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--ink-faint);
  font-size: 10px;
  cursor: pointer;
  transition: background-color 150ms ease, color 150ms ease;
}

.icon-text-button:hover {
  background: var(--surface);
  color: var(--ink);
}

.fb-done {
  color: var(--success);
  font-size: 10px;
}

/* 输入区 */
.composer-wrap {
  flex: 0 0 auto;
  padding: 10px 28px 14px;
  background: var(--surface-raised);
}

.composer {
  width: min(780px, 100%);
  margin: 0 auto;
  padding: 11px 12px 9px 15px;
  border: 1px solid var(--line-strong);
  border-radius: 11px;
  background: var(--surface);
  transition: border-color 160ms ease, box-shadow 160ms ease;
}

.composer:focus-within {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgb(36 59 52 / 7%);
}

.composer textarea {
  display: block;
  width: 100%;
  max-height: 140px;
  padding: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--ink);
  font-size: 13.5px;
  line-height: 1.7;
  resize: none;
}

.composer textarea::placeholder {
  color: var(--ink-faint);
}

.composer-foot {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  margin-top: 8px;
}

.composer-note {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--ink-faint);
  font-size: 9.5px;
}

.char-count {
  font-family: var(--mono);
}

.char-count.near {
  color: var(--warning);
}

.send-button {
  display: grid;
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  place-items: center;
  border: 0;
  border-radius: 8px;
  background: var(--primary);
  color: #f7f4ed;
  cursor: pointer;
  transition: background-color 160ms ease, opacity 160ms ease;
}

.send-button:hover:not(:disabled) {
  background: var(--primary-hover);
}

.send-button:disabled {
  cursor: not-allowed;
  opacity: 0.32;
}

.send-button.stop {
  background: var(--ink-soft);
}

.composer-disclaimer {
  width: min(780px, 100%);
  margin: 7px auto 0;
  color: var(--ink-faint);
  font-size: 9.5px;
  text-align: center;
}

/* 依据栏 */
.context-pane {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  border-left: 1px solid var(--line);
  background: var(--paper);
}

.context-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 22px 20px 8px;
}

.context-head .eyebrow {
  margin-bottom: 3px;
}

.context-head h2 {
  margin: 0;
  font-family: var(--serif);
  font-size: 20px;
  font-weight: 600;
}

.context-close {
  display: none;
}

.context-tabs {
  display: flex;
  gap: 18px;
  margin: 8px 20px 0;
  border-bottom: 1px solid var(--line-strong);
}

.context-tabs button {
  position: relative;
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 8px 0 10px;
  border: 0;
  background: transparent;
  color: var(--ink-muted);
  font-size: 11.5px;
  cursor: pointer;
  transition: color 150ms ease;
}

.context-tabs button::after {
  position: absolute;
  right: 0;
  bottom: -1px;
  left: 0;
  height: 2px;
  background: transparent;
  content: "";
}

.context-tabs button.active {
  color: var(--ink);
  font-weight: 600;
}

.context-tabs button.active::after {
  background: var(--primary);
}

.context-tabs button span {
  color: var(--ink-faint);
  font-family: var(--mono);
  font-size: 9px;
  font-weight: 400;
}

.context-scroll {
  flex: 1;
  min-height: 0;
  padding: 14px 16px 22px;
  overflow-y: auto;
}

.context-empty {
  display: flex;
  height: 100%;
  min-height: 220px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--ink-faint);
  text-align: center;
}

.context-empty p {
  max-width: 190px;
  margin: 0;
  font-size: 11px;
  line-height: 1.7;
}

.evidence-card {
  margin-bottom: 10px;
  padding: 13px 13px 11px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface-raised);
  transition: border-color 160ms ease;
}

.evidence-card:hover {
  border-color: var(--line-strong);
}

.evidence-head {
  display: flex;
  align-items: flex-start;
  gap: 9px;
}

.evidence-ref {
  display: grid;
  width: 22px;
  height: 22px;
  flex: 0 0 auto;
  place-items: center;
  border: 1px solid var(--line-strong);
  border-radius: 50%;
  color: var(--primary);
  font-family: var(--mono);
  font-size: 8px;
}

.evidence-title {
  min-width: 0;
  flex: 1;
}

.evidence-title h3 {
  margin: 0;
  color: var(--ink-soft);
  font-size: 12px;
  font-weight: 600;
  line-height: 1.5;
}

.evidence-title p {
  margin: 2px 0 0;
  color: var(--ink-faint);
  font-size: 9.5px;
  line-height: 1.5;
}

.evidence-score {
  color: var(--ink-faint);
  font-family: var(--mono);
  font-size: 9px;
}

.evidence-text {
  display: -webkit-box;
  margin: 9px 0 0;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 4;
  color: var(--ink-muted);
  font-size: 11px;
  line-height: 1.8;
  white-space: pre-wrap;
}

.evidence-card.expanded .evidence-text {
  display: block;
  overflow: visible;
}

.text-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-top: 7px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--ink-muted);
  font-size: 9.5px;
  text-decoration: underline;
  text-decoration-color: var(--line-strong);
  text-underline-offset: 3px;
  cursor: pointer;
}

.text-link:hover {
  color: var(--primary);
  text-decoration-color: var(--primary);
}

.checklist-summary {
  margin-bottom: 12px;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface-raised);
}

.summary-numbers {
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.summary-numbers strong {
  font-family: var(--serif);
  font-size: 27px;
  font-weight: 600;
  line-height: 1;
}

.summary-numbers span {
  color: var(--ink-muted);
  font-size: 10px;
}

.progress-track {
  height: 3px;
  margin: 12px 0 9px;
  overflow: hidden;
  border-radius: 2px;
  background: var(--paper-deep);
}

.progress-track span {
  display: block;
  height: 100%;
  background: var(--primary);
  transition: width 200ms ease;
}

.summary-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: var(--ink-faint);
  font-size: 9px;
}

.export {
  margin: 0;
  color: var(--ink-soft);
  text-decoration: none;
}

.check-row {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  padding: 10px 8px;
  border-bottom: 1px solid var(--line);
  cursor: pointer;
}

.check-row:hover {
  background: rgb(255 255 255 / 56%);
}

.check-row input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
}

.check-box {
  display: grid;
  width: 17px;
  height: 17px;
  flex: 0 0 auto;
  margin-top: 1px;
  place-items: center;
  border: 1px solid var(--line-strong);
  border-radius: 3px;
  background: var(--surface-raised);
  color: transparent;
  transition: background-color 150ms ease, border-color 150ms ease, color 150ms ease;
}

.check-row input:checked + .check-box {
  border-color: var(--primary);
  background: var(--primary);
  color: #fff;
}

.check-row input:focus-visible + .check-box {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}

.check-body {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 3px;
}

.check-body small {
  color: var(--ink-faint);
  font-family: var(--mono);
  font-size: 8px;
  letter-spacing: 0.08em;
}

.check-body > span {
  color: var(--ink-soft);
  font-size: 11.5px;
  line-height: 1.65;
  overflow-wrap: anywhere;
}

.check-body > span.done {
  color: var(--ink-faint);
  text-decoration: line-through;
}

.scrim {
  position: fixed;
  z-index: 45;
  inset: var(--header-h) 0 0;
  display: none;
  border: 0;
  background: rgb(27 26 22 / 28%);
  backdrop-filter: blur(1px);
}

@media (max-width: 1180px) {
  .chat-page {
    grid-template-columns: 240px minmax(0, 1fr);
  }

  .context-toggle {
    display: inline-flex;
  }

  .context-pane {
    position: fixed;
    z-index: 50;
    top: var(--header-h);
    right: 0;
    bottom: 0;
    width: min(390px, 92vw);
    border-left: 1px solid var(--line-strong);
    box-shadow: -12px 0 36px rgb(27 26 22 / 10%);
    transform: translateX(102%);
    transition: transform 220ms ease;
  }

  .context-pane.open {
    transform: translateX(0);
  }

  .context-close {
    display: inline-grid;
  }

  .scrim {
    display: block;
  }
}

@media (max-width: 860px) {
  .chat-page {
    grid-template-columns: minmax(0, 1fr);
    height: calc(100dvh - 60px - 58px);
  }

  .session-rail {
    position: fixed;
    z-index: 50;
    top: 60px;
    bottom: 58px;
    left: 0;
    width: min(300px, 86vw);
    border-right: 1px solid var(--line-strong);
    box-shadow: 12px 0 36px rgb(27 26 22 / 10%);
    transform: translateX(-102%);
    transition: transform 220ms ease;
  }

  .session-rail.open {
    transform: translateX(0);
  }

  .rail-close,
  .mobile-only {
    display: inline-grid;
  }

  .context-pane {
    top: 60px;
    bottom: 58px;
  }

  .scrim {
    inset: 60px 0 58px;
  }

  .thread-bar {
    min-height: 50px;
    padding: 0 16px;
  }

  .welcome {
    padding: 6vh 22px 32px;
  }

  .messages {
    padding: 26px 20px 20px;
  }

  .composer-wrap {
    padding: 8px 14px 10px;
  }

  .composer-disclaimer {
    display: none;
  }

  .user-question {
    max-width: 88%;
  }

  .answer-footer {
    align-items: flex-start;
    flex-direction: column;
    gap: 5px;
  }
}

@media (max-width: 720px) {
  .starter-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .starter:nth-child(odd) {
    border-right: 0;
  }

  .starter {
    padding: 13px 4px;
  }
}

@media (max-width: 560px) {
  .welcome {
    padding-top: 4vh;
  }

  .welcome-title {
    font-size: 31px;
  }

  .welcome-lead {
    margin-top: 14px;
    font-size: 12.5px;
  }

  .starter-head {
    margin-top: 26px;
  }

  .starter-copy strong {
    font-size: 12.5px;
  }

  .messages {
    padding: 22px 16px 16px;
  }

  .message {
    margin-bottom: 26px;
  }

  .answer-text {
    font-size: 14px;
    line-height: 1.88;
  }

  .composer textarea {
    font-size: 13px;
  }

  .composer-note > span:first-child {
    display: none;
  }

  .context-pane {
    width: 100vw;
  }
}
</style>
