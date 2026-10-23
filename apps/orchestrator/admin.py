"""会话留痕只读。运营侧要看"用户问了什么、我们答了什么"，但不该在这里改。"""

from django.contrib import admin

from apps.orchestrator.models import Conversation, Message


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    can_delete = False
    fields = ("turn", "role", "intent", "answerable", "refusal_reason", "latency_ms", "trace_id")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "user_key", "title", "audience", "turn_count", "last_active_at")
    list_filter = ("audience",)
    search_fields = ("title", "user_key")
    inlines = [MessageInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("conversation_id", "turn", "role", "intent", "answerable", "latency_ms")
    list_filter = ("role", "answerable", "refusal_reason")
    search_fields = ("content", "trace_id")
    readonly_fields = [f.name for f in Message._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
