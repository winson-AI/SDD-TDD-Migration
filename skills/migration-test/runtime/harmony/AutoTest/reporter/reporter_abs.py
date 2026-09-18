from abc import ABC, abstractmethod


class ReporterAbs(ABC):
    """
    报告器抽象基类

    定义测试报告生成器的接口规范，用于记录测试过程中各个阶段的事件。
    子类需要实现所有抽象方法来定义具体的报告行为（如生成 HTML、JSON、日志等）。

    事件分为两个层次：
    - Planner（决策层）：负责任务分解、LLM 调用、工具选择
    - Execute Agent（执行层）：负责具体动作的执行
    """

    # ==================== Planner（决策层）事件 ====================

    @abstractmethod
    def planner_agent_start(self, *args, **kwargs) -> None:
        """
        决策代理启动事件

        当分层决策代理开始处理一个任务时触发
        """
        ...

    @abstractmethod
    def planner_agent_end(self, *args, **kwargs) -> None:
        """
        决策代理结束事件

        当分层决策代理完成一个任务的处理时触发
        """
        ...

    @abstractmethod
    def planner_llm_start(self, *args, **kwargs) -> None:
        """
        LLM 调用开始事件

        当决策层调用大语言模型时触发
        """
        ...

    @abstractmethod
    def planner_llm_end(self, *args, **kwargs) -> None:
        """
        LLM 调用结束事件

        当大语言模型返回结果时触发
        """
        ...

    @abstractmethod
    def planner_tools_start(self, *args, **kwargs) -> None:
        """
        工具调用开始事件

        当决策层准备调用工具时触发
        """
        ...

    @abstractmethod
    def planner_tools_end(self, *args, **kwargs) -> None:
        """
        工具调用结束事件

        当工具执行完成并返回结果时触发
        """
        ...

    # ==================== Execute Agent（执行层）事件 ====================

    @abstractmethod
    def execute_agent_step_start(self, *args, **kwargs) -> None:
        """
        执行步骤开始事件

        当执行代理开始一个完整步骤时触发（一个步骤可能包含多个动作）
        """
        ...

    @abstractmethod
    def execute_agent_do_start(self, *args, **kwargs) -> None:
        """
        执行动作开始事件

        当执行代理开始单个具体动作时触发（如点击、滑动等）
        """
        ...

    @abstractmethod
    def execute_agent_do_end(self, *args, **kwargs) -> None:
        """
        执行动作结束事件

        当单个具体动作执行完成时触发
        """
        ...

    @abstractmethod
    def execute_agent_step_end(self, *args, **kwargs) -> None:
        """
        执行步骤结束事件

        当执行代理完成一个完整步骤时触发
        """
        ...

    # ==================== Task（任务层）事件 ====================

    @abstractmethod
    def task_start(self, *args, **kwargs) -> None:
        """
        任务开始事件

        当整个测试任务开始时触发（最高层级事件）
        """
        ...

    @abstractmethod
    def task_end(self, *args, **kwargs) -> None:
        """
        任务结束事件

        当整个测试任务完成时触发（无论成功或失败）
        """
        ...

    @abstractmethod
    def token_usage(self, *args, **kwargs) -> None:
        """
        token统计事件
        """
        ...

    @abstractmethod
    def verify_start(self, *args, **kwargs) -> None:
        """
        验证开始
        """
        ...

    @abstractmethod
    def verify_end(self, *args, **kwargs) -> None:
        """
        验证结束
        """
        ...