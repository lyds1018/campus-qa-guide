<script setup lang="ts">
import { ElMessage } from "element-plus";
import { onMounted, reactive, ref } from "vue";

import { ops, type MatterRow, type TermRow } from "../../api/ops";

const matters = ref<MatterRow[]>([]);
const terms = ref<TermRow[]>([]);
const query = ref("");
const termQuery = ref("");
const dialog = ref(false);
const saving = ref(false);
const form = reactive<Partial<MatterRow>>({});

const termDialog = ref(false);
const termForm = reactive<Partial<TermRow>>({ term: "", canonical: "", term_type: "alias", weight: 1 });

async function loadMatters() {
  try {
    matters.value = await ops.matters(query.value);
  } catch (e) {
    ElMessage.error((e as { detail?: string }).detail ?? "加载事项失败");
  }
}

async function loadTerms() {
  try {
    terms.value = await ops.terms(termQuery.value);
  } catch (e) {
    ElMessage.error((e as { detail?: string }).detail ?? "加载词典失败");
  }
}

function edit(row?: MatterRow) {
  Object.keys(form).forEach((k) => delete (form as Record<string, unknown>)[k]);
  Object.assign(form, row ?? { name: "", dept: "", location: "", contact: "", summary: "" });
  dialog.value = true;
}

async function saveMatter() {
  if (!form.name) {
    ElMessage.warning("事项名称必填");
    return;
  }
  saving.value = true;
  try {
    await ops.saveMatter({ ...form });
    ElMessage.success("已保存（词典与答案缓存会随之失效）");
    dialog.value = false;
    await loadMatters();
  } catch (e) {
    ElMessage.error((e as { detail?: string }).detail ?? "保存失败");
  } finally {
    saving.value = false;
  }
}

async function addTerm() {
  if (!termForm.term || !termForm.canonical) {
    ElMessage.warning("别名与规范名都要填");
    return;
  }
  try {
    await ops.saveTerms([{ ...termForm }]);
    ElMessage.success("已添加，改写缓存已失效");
    termDialog.value = false;
    termForm.term = "";
    termForm.canonical = "";
    await loadTerms();
  } catch (e) {
    ElMessage.error((e as { detail?: string }).detail ?? "添加失败");
  }
}

async function removeTerm(id: number) {
  try {
    await ops.deleteTerm(id);
    await loadTerms();
  } catch (e) {
    ElMessage.error((e as { detail?: string }).detail ?? "删除失败");
  }
}

onMounted(async () => {
  await Promise.all([loadMatters(), loadTerms()]);
});
</script>

<template>
  <div class="tab-body">
    <el-card shadow="never">
      <template #header>
        <div class="head">
          <span>事项库（M7 的匹配源）</span>
          <div class="search">
            <el-input v-model="query" placeholder="按名称搜索" clearable style="width: 180px" />
            <el-button size="small" @click="loadMatters">查询</el-button>
            <el-button size="small" type="primary" @click="edit()">新建事项</el-button>
          </div>
        </div>
      </template>
      <el-table :data="matters" size="small" empty-text="还没有事项">
        <el-table-column prop="code" label="编号" width="120" />
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column prop="dept" label="部门" width="130" />
        <el-table-column prop="audience" label="面向" width="90" />
        <el-table-column prop="status" label="状态" width="90" />
        <el-table-column prop="steps" label="步骤" width="70" />
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="edit(row)">编辑</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="head">
          <span>词典（M5 的改写源）</span>
          <div class="search">
            <el-input v-model="termQuery" placeholder="别名或规范名" clearable style="width: 180px" />
            <el-button size="small" @click="loadTerms">查询</el-button>
            <el-button size="small" type="primary" @click="termDialog = true">新增别名</el-button>
          </div>
        </div>
      </template>
      <el-table :data="terms" size="small" empty-text="词典为空">
        <el-table-column prop="term" label="别名" min-width="140" />
        <el-table-column prop="canonical" label="规范名" min-width="140" />
        <el-table-column prop="term_type" label="类型" width="100" />
        <el-table-column prop="weight" label="权重" width="80" />
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button size="small" text type="danger" @click="removeTerm(row.id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialog" :title="form.code ? '编辑事项' : '新建事项'" width="560px">
      <el-form label-width="80px">
        <el-form-item label="编号"><el-input v-model="form.code" placeholder="留空自动生成" /></el-form-item>
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="部门"><el-input v-model="form.dept" /></el-form-item>
        <el-form-item label="面向">
          <el-select v-model="form.audience" clearable placeholder="不限">
            <el-option label="本科生" value="undergrad" />
            <el-option label="研究生" value="grad" />
            <el-option label="教职工" value="staff" />
            <el-option label="校友" value="alumni" />
          </el-select>
        </el-form-item>
        <el-form-item label="地点"><el-input v-model="form.location" /></el-form-item>
        <el-form-item label="联系电话"><el-input v-model="form.contact" /></el-form-item>
        <el-form-item label="概述">
          <el-input v-model="form.summary" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveMatter">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="termDialog" title="新增别名" width="460px">
      <el-form label-width="80px">
        <el-form-item label="别名"><el-input v-model="termForm.term" placeholder="如一卡通" /></el-form-item>
        <el-form-item label="规范名">
          <el-input v-model="termForm.canonical" placeholder="如 校园卡" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="termForm.term_type">
            <el-option label="别名" value="alias" />
            <el-option label="简称" value="abbr" />
            <el-option label="同义词" value="synonym" />
          </el-select>
        </el-form-item>
        <el-form-item label="权重">
          <el-input-number v-model="termForm.weight" :min="1" :max="9" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="termDialog = false">取消</el-button>
        <el-button type="primary" @click="addTerm">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.tab-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.search {
  display: flex;
  gap: 8px;
}
</style>
