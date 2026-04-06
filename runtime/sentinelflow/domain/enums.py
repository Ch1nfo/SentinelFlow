from enum import Enum


class SkillType(str, Enum):
    DOC = "doc"
    HYBRID = "hybrid"


class SkillRuntimeMode(str, Enum):
    SUBPROCESS = "subprocess"
    PYTHON_CALLABLE = "python_callable"
    WORKFLOW = "workflow"


class AlertDisposition(str, Enum):
    TRUE_ATTACK = "true_attack"
    BUSINESS_TRIGGER = "business_trigger"
    FALSE_POSITIVE = "false_positive"
