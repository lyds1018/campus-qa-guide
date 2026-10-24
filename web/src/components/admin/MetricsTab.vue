<script setup lang="ts">
import { ElMessage } from "element-plus";
import { onMounted, ref } from "vue";

import { ops, type EvalRunRow, type FeedbackRow, type Metrics } from "../../api/ops";

const metrics = ref<Metrics | null>(null);
const feedback = ref<FeedbackRow[]>([]);
const runs = ref<EvalRunRow[]>([]);
const loading = ref(false);

const REASON_LABEL: Record<string, string> = {
  wrong_fact: "口径/数字错",
  incomplete: "答不全",
  off_topic: "答非所问",
  outdated: "信息过期",
  other: "其他",
  "": "未填",
};

// 演练记录只有"作答/兜底/降级"，没有 hit@3 这类指标：缺值显示 — 而不是 0%
const pct = (value?: number) => (value === undefined ? "—" : `${Math.round(value * 100)}%`);

async function load() {
  loading.value = true;
  try {
    const [m, fb, ev] = await Promise.all([ops.metrics(7), ops.feedbackList(), ops.evals()]);
    metrics.value = m;
    feedback.value = fb;
    runs.value = ev;
  } catch (e) {
    ElMessage.error((e as { detail?: string }).detail ?? "加载评测数据失败");
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="tab-body" v-loading="loading">
    <div class="metric-grid">
      <article class="metric-card">
        <span class="metric-kicker">近 7 天问答</span>
        <strong>{{ metrics?.qa.turns ?? 0 }}</strong>
        <p>拒答 {{ metrics?.qa.refused ?? 0 }} 次</p>
      </article>
      <article class="metric-card">
        <span class="metric-kicker">拒答率</span>
        <strong>{{ metrics?.qa.refusal_rate ?? 0 }}<small>%</small></strong>
        <p>P50 {{ metrics?.qa.p50_ms ?? 0 }}ms</p>
      </article>
      <article class="metric-card">
        <span class="metric-kicker">反馈</span>
        <strong>{{ metrics?.feedback.down ?? 0 }}<small>/ {{ metrics?.feedback.total ?? 0 }}</small></strong>
        <p>差评数 / 反馈总数</p>
      </article>
      <article class="metric-card">
        <span class="metric-kicker">最近回归 hit@3</span>
        <strong>{{ pct(runs.find((r) => r.kind === "eval")?.metrics.hit_at_3) }}</strong>
        <p>黄金集 {{ metrics?.golden.samples ?? 0 }} 条</p>
      </article>
    </div>

    <el-card shadow="never">
      <template #header>
        <div class="head">
          <span>回归与演练档案</span>
          <el-button size="small" @click="load">刷新</el-button>
        </div>
      </template>
      <el-table :data="runs" size="small" empty-text="还没有跑过回归">
        <el-table-column label="类型" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.kind === 'eval' ? 'primary' : 'warning'">
              {{ row.kind === "eval" ? "回归" : "演练" }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="label" label="标签" width="130" />
        <el-table-column prop="samples" label="样本" width="70" />
        <el-table-column label="hit@3" width="80">
          <template #default="{ row }">{{ pct(row.metrics.hit_at_3) }}</template>
        </el-table-column>
        <el-table-column label="可答判对" width="90">
          <template #default="{ row }">{{ pct(row.metrics.answer_ok) }}</template>
        </el-table-column>
        <el-table-column label="拒答判对" width="90">
          <template #default="{ row }">{{ pct(row.metrics.refuse_ok) }}</template>
        </el-table-column>
        <el-table-column label="P50" width="80">
          <template #default="{ row }">
            {{ row.metrics.latency_p50_ms === undefined ? "—" : `${row.metrics.latency_p50_ms}ms` }}
          </template>
        </el-table-column>
        <el-table-column label="成本" width="90">
          <template #default="{ row }">¥{{ row.cost.toFixed(4) }}</template>
        </el-table-column>
        <el-table-column prop="finished_at" label="完成时间" min-width="170" />
      </el-table>
      <div class="footnote">
        回归与演练走命令行（p7_eval / p7_drill），这里只读历史；报告为 markdown，路径见
        EVAL_REPORT_DIR。
      </div>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="head">
          <span>学生反馈</span>
          <span class="table-note">差评优先复核</span>
        </div>
      </template>
      <el-table :data="feedback" size="small" empty-text="还没有反馈">
        <el-table-column prop="question" label="问题" min-width="200" show-overflow-tooltip />
        <el-table-column label="评分" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.rating === 'down' ? 'danger' : 'success'">
              {{ row.rating === "down" ? "没用" : "有用" }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="原因" width="120">
          <template #default="{ row }">{{ REASON_LABEL[row.reason] ?? row.reason }}</template>
        </el-table-column>
        <el-table-column label="应可答" width="90">
          <template #default="{ row }">
            {{ row.expect === "answer" ? "应可答" : row.expect === "refuse" ? "应拒答" : "说不清" }}
          </template>
        </el-table-column>
        <el-table-column prop="note" label="补充" min-width="140" show-overflow-tooltip />
        <el-table-column prop="trace_id" label="trace" width="120" show-overflow-tooltip />
        <el-table-column prop="created_at" label="时间" min-width="160" />
      </el-table>
      <div class="footnote">
        差评是候选池，不是黄金集：确认后执行 p7_golden --apply 才进入回归基线。
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface-raised);
}

.metric-card {
  min-width: 0;
  padding: 18px 18px 16px;
  border-right: 1px solid var(--line);
}

.metric-card:last-child {
  border-right: 0;
}

.metric-kicker {
  display: block;
  color: var(--ink-muted);
  font-family: var(--mono);
  font-size: 9px;
  letter-spacing: 0.08em;
}

.metric-card strong {
  display: block;
  margin-top: 10px;
  color: var(--ink);
  font-family: var(--serif);
  font-size: 30px;
  font-weight: 600;
  line-height: 1;
}

.metric-card strong small {
  margin-left: 3px;
  color: var(--ink-muted);
  font-family: var(--sans);
  font-size: 10px;
  font-weight: 400;
}

.metric-card p {
  margin: 8px 0 0;
  color: var(--ink-faint);
  font-size: 9.5px;
  line-height: 1.55;
}

.table-note {
  color: var(--ink-faint);
  font-size: 9.5px;
  font-weight: 400;
}

.footnote {
  margin-top: 10px;
  color: var(--ink-faint);
  font-size: 9.5px;
  line-height: 1.65;
}

@media (max-width: 1080px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .metric-card:nth-child(2) {
    border-right: 0;
  }

  .metric-card:nth-child(-n + 2) {
    border-bottom: 1px solid var(--line);
  }
}

@media (max-width: 620px) {
  .table-note {
    display: none;
  }
}
</style>
