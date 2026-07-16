from django.contrib import admin

from .models import (
    AgentExecution,
    AgentProfile,
    AgentVersion,
    ApprovalRequest,
    AssignmentPool,
    BudgetPolicy,
    DataScope,
    EscalationPolicy,
    ExecutionStep,
    Operator,
    PerformanceMetric,
    Team,
    TeamMembership,
    ToolPermission,
    WorkItem,
)

admin.site.register(
    [
        Operator,
        Team,
        TeamMembership,
        AssignmentPool,
        AgentProfile,
        AgentVersion,
        ToolPermission,
        DataScope,
        WorkItem,
        BudgetPolicy,
        EscalationPolicy,
        AgentExecution,
        ExecutionStep,
        ApprovalRequest,
        PerformanceMetric,
    ]
)
