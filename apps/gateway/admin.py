"""台账只读视图。不做编辑：ai_calls 由网关自动写入，人工改会破坏指标口径。"""

from django.contrib import admin

from apps.gateway.models import AICall


@admin.register(AICall)
class AICallAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "created_at",
        "task",
        "provider",
        "model",
        "status",
        "attempt",
        "cached",
        "latency_ms",
        "cost",
    )
    list_filter = ("task", "status", "provider", "cached")
    search_fields = ("trace_id", "model", "error_code")
    date_hierarchy = "created_at"
    ordering = ("-id",)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False
