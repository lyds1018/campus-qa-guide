"""只读 Admin：P1 只用于查看入库结果，编辑与发布走 P6 的运营界面。"""

from django.contrib import admin

from apps.knowledge.models import Chunk, Document, Flow, IngestJob, Matter, Term


class ReadOnlyAdmin(admin.ModelAdmin):
    actions = None

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(Document)
class DocumentAdmin(ReadOnlyAdmin):
    list_display = (
        "id",
        "title",
        "doc_type",
        "dept",
        "version",
        "status",
        "page_count",
        "created_at",
    )
    list_filter = ("doc_type", "status", "dept")
    search_fields = ("title", "source_path", "checksum")


@admin.register(Chunk)
class ChunkAdmin(ReadOnlyAdmin):
    list_display = ("id", "document", "ordinal", "status", "char_len", "has_embedding")
    list_filter = ("status",)
    search_fields = ("content",)

    @admin.display(description="字数")
    def char_len(self, obj: Chunk) -> int:
        return len(obj.content)

    @admin.display(boolean=True, description="有向量")
    def has_embedding(self, obj: Chunk) -> bool:
        return obj.embedding is not None


@admin.register(Matter)
class MatterAdmin(ReadOnlyAdmin):
    list_display = ("code", "name", "dept", "category", "status", "version")
    list_filter = ("status", "dept")
    search_fields = ("code", "name")


@admin.register(Flow)
class FlowAdmin(ReadOnlyAdmin):
    list_display = ("matter", "step_no", "title", "channel", "duration_hint")
    list_filter = ("channel",)


@admin.register(Term)
class TermAdmin(ReadOnlyAdmin):
    list_display = ("term", "canonical", "term_type", "weight")
    list_filter = ("term_type",)
    search_fields = ("term", "canonical")


@admin.register(IngestJob)
class IngestJobAdmin(ReadOnlyAdmin):
    list_display = ("id", "source_path", "status", "stage", "message", "created_at")
    list_filter = ("status", "stage")
    search_fields = ("source_path", "message")
