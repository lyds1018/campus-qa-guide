"""全局唯一的 NinjaAPI 实例，各 app 用 Router 挂进来。"""

from ninja import NinjaAPI

api = NinjaAPI(title="校园智能问答与办事指南 API", version="0.1.0", docs_url="/docs")
api.add_router("/health", "apps.common.api.router")
api.add_router("/kb", "apps.knowledge.api.router")
api.add_router("/gw", "apps.gateway.api.router")
api.add_router("/qa", "apps.qa.api.router")
