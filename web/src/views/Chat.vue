<script setup lang="ts">
import { ElMessage } from "element-plus";
import { computed, nextTick, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { exportChecklist, history, saveBlob, sessions, streamChat } from "../api/chat";
import type { ChecklistItem, EvidenceItem, SessionBrief, TurnResult } from "../api/types";

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
const tab = ref("evidence");
const checked = ref<Record<string, boolean>>({});
const scroller = ref<HTMLElement>();

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

const STAGE_TEXT: Record<string, string> = {
  understand: "理解问题",
  route: "规划回答",
  fanout: "并行检索",
  retrieve: "检索资料",
  generate: "生成回答",
};

function stageLabel(stage: string): string {
  return STAGE_TEXT[stage] ?? stage;
}

const KIND_LABEL: Record<string, string> = {
  material: "材料",
  step: "步骤",
  condition: "条件",
  notice: "提示",
};

function itemKey(item: ChecklistItem): string {
  return `${item.kind}-${item.ordinal}`;
}

function isChecked(item: ChecklistItem): boolean {
  return checked.value[itemKey(item)] ?? false;
}

function toggle(item: ChecklistItem) {
  checked.value = { ...checked.value, [itemKey(item)]: !isChecked(item) };
}

async function scrollToBottom() {
  await nextTick();
  if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight;
}

async function refreshSessions() {
  try {
    list.value = await sessions(20);
  } catch {
    /* 侧栏失败不影响对话 */
  }
}

function newChat() {
  conversationId.value = null;
  messages.value = [];
  checked.value = {};
  tab.value = "evidence";
}

async function openSession(id: string) {
  try {
    const rows = await history(id);
    conversationId.value = id;
    checked.value = {};
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
    await scrollToBottom();
  } catch (e) {
    ElMessage.error((e as { detail?: string }).detail ?? "加载会话失败");
  }
}

async function send() {
  const text = question.value.trim();
  if (!text || streaming.value) return;
  question.value = "";
  messages.value.push({ role: "user", text, notices: [] });
  const bubble: Bubble = { role: "assistant", text: "", notices: [], pending: true };
  messages.value.push(bubble);
  streaming.value = true;
  await scrollToBottom();

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
          bubble.text = d.text;          // 用装配后的完整文本覆盖流式片段
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
    );
  } catch (e) {
    const err = e as { status?: number; detail?: string };
    bubble.error = err.status === 429 ? "请求过于频繁，请稍后再试" : err.detail ?? "请求失败";
  } finally {
    streaming.value = false;
    bubble.pending = false;
    bubble.stage = undefined;
    await refreshSessions();
    await scrollToBottom();
  }
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

onMounted(async () => {
  await refreshSessions();
  // 深链：/chat?c=<conversation_id> 直接打开某次会话，便于分享与排查
  const deepLink = route.query.c;
  if (typeof deepLink === "string" && deepLink) await openSession(deepLink);
});
</script>

<template>
  <div class="chat-layout">
    <aside class="sidebar">
      <el-button class="new-btn" type="primary" plain @click="newChat">＋ 新对话</el-button>
      <el-scrollbar class="session-list">
        <div
          v-for="item in list"
          :key="item.id"
          class="session-item"
          :class="{ active: item.id === conversationId }"
          @click="openSession(item.id)"
        >
          <div class="title">{{ item.title || "未命名会话" }}</div>
          <div class="sub">{{ item.turn_count }} 轮</div>
        </div>
        <el-empty v-if="!list.length" description="还没有历史会话" :image-size="60" />
      </el-scrollbar>
    </aside>

    <section class="dialog">
      <div ref="scroller" class="messages">
        <div v-if="!messages.length" class="welcome">
          <h2>校园办事问答</h2>
          <p>问一句就行，例如：学生证丢了怎么补办 / 国家奖学金的奖励标准是多少</p>
        </div>

        <div v-for="(m, i) in messages" :key="i" class="row" :class="m.role">
          <div v-if="m.role === 'user'" class="user-bubble">{{ m.text }}</div>
          <div v-else class="answer">
            <div v-if="m.pending && !m.text" class="thinking">
              {{ m.stage ? `正在${stageLabel(m.stage)}…` : "正在思考…" }}
            </div>
            <div v-else class="answer-text">{{ m.text }}</div>
            <div v-if="m.result" class="answer-meta">
              <el-tag size="small" :type="m.result.answerable ? 'success' : 'info'">
                {{ m.result.answerable ? "有依据作答" : "未作答" }}
              </el-tag>
              <el-tag v-if="m.result.mode === 'fanout'" size="small" type="warning">多问题并行</el-tag>
              <el-tag v-if="m.result.degraded" size="small" type="warning">备用模型</el-tag>
              <span class="latency">{{ m.result.latency_ms }}ms</span>
            </div>
            <ul v-if="m.notices.length" class="notices">
              <li v-for="(n, k) in m.notices" :key="k">{{ n }}</li>
            </ul>
            <div v-if="m.error" class="error">⚠ {{ m.error }}</div>
          </div>
        </div>
      </div>

      <div class="composer">
        <el-input
          v-model="question"
          type="textarea"
          :rows="2"
          resize="none"
          placeholder="输入问题，Enter 发送，Shift+Enter 换行"
          @keydown.enter.exact.prevent="send"
        />
        <el-button type="primary" :loading="streaming" @click="send">发送</el-button>
      </div>
    </section>

    <aside class="pane">
      <el-tabs v-model="tab" class="pane-tabs">
        <el-tab-pane :label="`原文依据 ${evidence.length}`" name="evidence">
          <el-scrollbar class="pane-body">
            <el-empty v-if="!evidence.length" description="作答后显示引用原文" :image-size="60" />
            <div v-for="item in evidence" :key="item.chunk_id" class="evidence">
              <div class="evidence-head">
                <span class="ref">[{{ item.ref }}]</span>
                <span class="doc">{{ item.title }}</span>
                <span class="section">{{ item.section }}</span>
              </div>
              <div class="evidence-meta">
                <span>第 {{ item.page }} 页</span>
                <span>相关度 {{ item.score.toFixed(2) }}</span>
                <span>{{ item.source }}</span>
              </div>
              <p class="evidence-text">{{ item.content }}</p>
            </div>
          </el-scrollbar>
        </el-tab-pane>

        <el-tab-pane :label="`办事清单 ${checklist.length}`" name="checklist">
          <div class="pane-body">
            <el-empty v-if="!checklist.length" description="问办事事项后生成清单" :image-size="60" />
            <template v-else>
              <div class="checklist-actions">
                <el-button size="small" type="primary" plain @click="doExport">导出 CSV</el-button>
                <span class="hint">勾选后会带进导出文件</span>
              </div>
              <div
                v-for="item in checklist"
                :key="itemKey(item)"
                class="check-row"
                @click="toggle(item)"
              >
                <el-checkbox :model-value="isChecked(item)" @click.stop="toggle(item)" />
                <div class="check-body">
                  <el-tag size="small" effect="plain">{{ KIND_LABEL[item.kind] ?? item.kind }}</el-tag>
                  <span :class="{ done: isChecked(item) }">{{ item.text }}</span>
                </div>
              </div>
            </template>
          </div>
        </el-tab-pane>
      </el-tabs>
    </aside>
  </div>
</template>

<style scoped>
.chat-layout {
  display: grid;
  grid-template-columns: 200px minmax(420px, 1fr) 380px;
  gap: 12px;
  height: calc(100vh - 96px);
  padding: 12px;
}

.sidebar,
.dialog,
.pane {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.sidebar {
  padding: 10px;
  gap: 8px;
}

.new-btn {
  width: 100%;
}

.session-list {
  flex: 1;
}

.session-item {
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  border: 1px solid transparent;
}

.session-item:hover {
  background: #f5f7fa;
}

.session-item.active {
  border-color: #409eff;
  background: #ecf5ff;
}

.session-item .title {
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-item .sub {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.welcome {
  color: #606266;
  text-align: center;
  margin-top: 80px;
}

.welcome h2 {
  font-size: 20px;
  margin-bottom: 8px;
}

.row {
  display: flex;
  margin-bottom: 14px;
}

.row.user {
  justify-content: flex-end;
}

.user-bubble {
  max-width: 70%;
  background: #409eff;
  color: #fff;
  padding: 10px 14px;
  border-radius: 10px 10px 2px 10px;
  white-space: pre-wrap;
}

.answer {
  max-width: 88%;
  background: #f7f9fc;
  border: 1px solid #ebeef5;
  border-radius: 10px 10px 10px 2px;
  padding: 12px 14px;
}

.answer-text {
  white-space: pre-wrap;
  line-height: 1.75;
  font-size: 14px;
}

.thinking {
  color: #909399;
  font-size: 13px;
}

.answer-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  font-size: 12px;
  color: #909399;
}

.notices {
  margin: 8px 0 0;
  padding-left: 18px;
  color: #b88230;
  font-size: 13px;
}

.error {
  margin-top: 8px;
  color: #f56c6c;
  font-size: 13px;
}

.composer {
  display: flex;
  gap: 8px;
  padding: 12px;
  border-top: 1px solid #ebeef5;
  align-items: flex-end;
}

.pane {
  min-width: 0;
}

.pane-tabs {
  padding: 0 8px 8px;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.pane-body {
  padding: 4px 4px 12px;
  max-height: calc(100vh - 190px);
  overflow-y: auto;
}

.evidence {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 10px;
  margin-bottom: 10px;
}

.evidence-head {
  display: flex;
  gap: 6px;
  align-items: baseline;
  font-size: 13px;
}

.evidence-head .ref {
  color: #409eff;
  font-weight: 600;
}

.evidence-head .doc {
  font-weight: 600;
}

.evidence-head .section {
  color: #909399;
  font-size: 12px;
}

.evidence-meta {
  display: flex;
  gap: 10px;
  color: #c0c4cc;
  font-size: 12px;
  margin: 4px 0;
}

.evidence-text {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  color: #303133;
  white-space: pre-wrap;
}

.checklist-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.checklist-actions .hint {
  font-size: 12px;
  color: #909399;
}

.check-row {
  display: flex;
  gap: 8px;
  padding: 8px;
  border-radius: 6px;
  cursor: pointer;
}

.check-row:hover {
  background: #f5f7fa;
}

.check-body {
  display: flex;
  gap: 6px;
  align-items: flex-start;
  font-size: 13px;
  line-height: 1.6;
}

.check-body .done {
  text-decoration: line-through;
  color: #c0c4cc;
}
</style>
