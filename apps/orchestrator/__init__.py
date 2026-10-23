"""编排调度层（L3，M4）：会话状态、意图路由、能力 fan-out、结果装配、SSE 事件。

对外只暴露 `apps.orchestrator.orchestrator.orc`；P5 在它之上加鉴权限流与页面。
"""
