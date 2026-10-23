"""知识资产层数据模型：文档库 / 块库 / 事项库（含流程）/ 词典库 + 入库任务表。

约定：
- 四库中只有 Document / Chunk 承载 P1 的语料，Matter / Flow / Term 只建表与种子词典；
- 发布态由 Document.status 决定，Chunk.status 随文档一起改，检索侧只看 published；
- Chunk.embedding 由 P2 回填，P1 留空。
"""

from django.conf import settings
from django.db import models
from pgvector.django import VectorField


class DocType(models.TextChoices):
    GUIDE = "guide", "办事指南"
    POLICY = "policy", "规章制度"
    FAQ = "faq", "常见问题"
    NOTICE = "notice", "通知公告"


class PublishStatus(models.TextChoices):
    DRAFT = "draft", "草稿"
    PUBLISHED = "published", "已发布"
    ARCHIVED = "archived", "已归档"


class Document(models.Model):
    """文档库：一份原件对应一行，checksum 唯一保证幂等。"""

    title = models.CharField(max_length=200)
    doc_type = models.CharField(max_length=16, choices=DocType.choices)
    dept = models.CharField(max_length=80, blank=True, default="")
    source_path = models.CharField(max_length=300)
    object_key = models.CharField(max_length=300)
    checksum = models.CharField(max_length=64, unique=True)
    mime = models.CharField(max_length=80, blank=True, default="")
    size = models.IntegerField(default=0)
    page_count = models.IntegerField(default=0)
    status = models.CharField(
        max_length=16, choices=PublishStatus.choices, default=PublishStatus.DRAFT
    )
    version = models.IntegerField(default=1)
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "documents"
        indexes = [
            models.Index(fields=["status", "doc_type"], name="idx_doc_status_type"),
            models.Index(fields=["title", "doc_type", "version"], name="idx_doc_title_type_ver"),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.title} v{self.version}"


class Chunk(models.Model):
    """块库：检索与引用的最小单元。search_text 存 jieba 分词结果供全文索引。"""

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="chunks")
    ordinal = models.IntegerField()
    content = models.TextField()
    search_text = models.TextField(default="", blank=True)
    meta = models.JSONField(default=dict, blank=True)
    embedding = VectorField(dimensions=settings.EMBEDDING_DIM, null=True)
    status = models.CharField(
        max_length=16, choices=PublishStatus.choices, default=PublishStatus.DRAFT
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "chunks"
        constraints = [
            models.UniqueConstraint(fields=["document", "ordinal"], name="uq_chunk_doc_ordinal"),
        ]
        indexes = [models.Index(fields=["status"], name="idx_chunk_status")]
        ordering = ["document_id", "ordinal"]

    def __str__(self) -> str:
        return f"{self.document_id}#{self.ordinal}"


class Matter(models.Model):
    """事项库：办事事项主表。P1 只建表，业务数据 P6 维护。"""

    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    dept = models.CharField(max_length=80, blank=True, default="")
    category = models.CharField(max_length=40, blank=True, default="")
    audience = models.CharField(max_length=16, blank=True, default="")  # undergrad/grad/staff
    summary = models.TextField(blank=True, default="")
    location = models.CharField(max_length=120, blank=True, default="")
    contact = models.CharField(max_length=80, blank=True, default="")
    status = models.CharField(
        max_length=16, choices=PublishStatus.choices, default=PublishStatus.DRAFT
    )
    version = models.IntegerField(default=1)
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "matters"
        indexes = [models.Index(fields=["status", "dept"], name="idx_matter_status_dept")]
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} {self.name}"


class Flow(models.Model):
    """流程库：事项下的步骤链。"""

    matter = models.ForeignKey(Matter, on_delete=models.CASCADE, related_name="flows")
    step_no = models.IntegerField()
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")
    materials = models.JSONField(default=list, blank=True)
    channel = models.CharField(max_length=16, default="both")  # online/offline/both
    duration_hint = models.CharField(max_length=40, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "flows"
        constraints = [
            models.UniqueConstraint(fields=["matter", "step_no"], name="uq_flow_matter_step"),
        ]
        ordering = ["matter_id", "step_no"]

    def __str__(self) -> str:
        return f"{self.matter_id} 第{self.step_no}步"


class Term(models.Model):
    """词典库：别名、简称、同义词，供 M5 做查询改写。"""

    term = models.CharField(max_length=80)
    canonical = models.CharField(max_length=80)
    term_type = models.CharField(max_length=16, default="alias")  # alias/abbr/synonym
    weight = models.SmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "terms"
        constraints = [
            models.UniqueConstraint(fields=["term", "canonical"], name="uq_term_canonical"),
        ]
        indexes = [models.Index(fields=["canonical"], name="idx_term_canonical")]

    def __str__(self) -> str:
        return f"{self.term} → {self.canonical}"


class JobStatus(models.TextChoices):
    PENDING = "pending", "待处理"
    RUNNING = "running", "处理中"
    SUCCEEDED = "succeeded", "成功"
    FAILED = "failed", "失败"
    SKIPPED = "skipped", "跳过"


class IngestJob(models.Model):
    """入库任务：状态落 PG 作为事实源，Redis 队列只投 job_id。"""

    source_path = models.CharField(max_length=300)  # 绝对路径，worker 直接读
    doc_type = models.CharField(max_length=16, default=DocType.GUIDE)
    dept = models.CharField(max_length=80, blank=True, default="")
    publish = models.BooleanField(default=False)
    document = models.ForeignKey(
        Document, on_delete=models.SET_NULL, null=True, blank=True, related_name="jobs"
    )
    status = models.CharField(
        max_length=16, choices=JobStatus.choices, default=JobStatus.PENDING
    )
    stage = models.CharField(max_length=16, blank=True, default="")  # parse/chunk/persist
    message = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ingest_jobs"
        indexes = [models.Index(fields=["status", "created_at"], name="idx_job_status_created")]
        ordering = ["-id"]

    def __str__(self) -> str:
        return f"job#{self.pk} {self.status} {self.source_path}"
