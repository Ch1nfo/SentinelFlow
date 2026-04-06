from enum import Enum

class AgentRole(str, Enum):
    PRIMARY = "primary"
    WORKER = "worker"

class AgentMode(str, Enum):
    PRIMARY = "primary"
    SUBAGENT = "subagent"

class OrchestrationStrategy(str, Enum):
    SELF_HANDLE = "self_handle"
    FINISH = "finish"
    DELEGATE = "delegate"
    SELF_EXECUTE = "self_execute"
    WORKFLOW = "workflow"
    DIRECT = "direct"

class SkillType(str, Enum):
    DOC = "doc"
    EXEC = "exec"
    HYBRID = "hybrid"
