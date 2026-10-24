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
    <el-row :gutter="12">
      <el-col :span="6">
        <el-card shadow="never">
          <div class="metric">{{ metrics?.qa.turns ?? 0 }}</div>
          <div class="metric-label">近 7 天问答 / 拒答 {{ metrics?.qa.refused ?? 0 }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never">
          <div class="metric">{{ metrics?.qa.refusal_rate ?? 0 }}%</div>
          <div class="metric-label">拒答率（P50 {{ metrics?.qa.p50_ms ?? 0 }}ms）</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never">
          <div class="metric">
            {{ metrics?.feedback.down ?? 0 }} / {{ metrics?.feedback.total ?? 0 }}
          </div>
          <div class="metric-label">差评数 / 反馈总数</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never">
          <div class="metric">
            {{ pct(runs.find((r) => r.kind === "eval")?.metrics.hit_at_3) }}
          </div>
          <div class="metric-label">
            最近一次回归 hit@3（黄金集 {{ metrics?.golden.samples ?? 0 }} 条）
          </div>
        </el-card>
      </el-col>
    </el-row>

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
      <div class="hint">
        回归与演练走命令行（`p7_eval` / `p7_drill`），这里只读历史；报告是 markdown，
        路径见 `EVAL_REPORT_DIR`。
      </div>
    </el-card>

    <el-card shadow="never">
      <template #header>用户反馈（差评优先看）</template>
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
      <div class="hint">
        差评是候选池、不是黄金集：确认后跑 `p7_golden --apply` 才进回归基线。
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.tab-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.metric {
  font-size: 26px;
  font-weight: 600;
  color: #303133;
}
.metric-label {
  margin-top: 4px;
  font-size: 12px;
  color: #909399;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.hint {
  margin-top: 8px;
  font-size: 12px;
  color: #909399;
}
</style>
