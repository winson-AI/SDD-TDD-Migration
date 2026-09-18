# 在 execute_agents/registry.py 中
class AgentRegistry:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def set_executor_agent(self, agent):
        self.executor_agent = agent

    def get_executor_agent(self):
        return getattr(self, 'executor_agent', None)

    def set_verify_agent(self, agent):
        self.verify_agent = agent

    def get_verify_agent(self):
        return getattr(self, 'verify_agent', None)

    def set_last_click_info(self, x: int, y: int, action: str = 'click'):
        self.last_click_info = {
            'x': x,
            'y': y,
            'action': action
        }

    def get_last_click_info(self):
        return getattr(self, 'last_click_info', None)

    def clear_last_click_info(self):
        self.last_click_info = None

    def set_last_click_cache(self, click_cache: dict):
        """保存完整的点击缓存信息（包括 xpath）。

        采用累积模式：execute 工具内部可能触发多次 click，
        每次都追加到列表，避免被后续步骤覆盖。
        """
        if not hasattr(self, 'last_click_caches') or self.last_click_caches is None:
            self.last_click_caches = []
        self.last_click_caches.append(click_cache)

    def get_last_click_caches(self) -> list:
        """获取本次 execute 期间累积的所有 click 缓存列表。"""
        return getattr(self, 'last_click_caches', None) or []

    def clear_last_click_cache(self):
        """清除点击缓存信息"""
        self.last_click_caches = []

    def set_knowledge(self, knowledge: str):
        """保存当前任务匹配到的知识库内容"""
        self.knowledge = knowledge

    def get_knowledge(self) -> str:
        """获取知识库内容，无则返回空字符串"""
        return getattr(self, 'knowledge', '')


# 全局实例
agent_registry = AgentRegistry()
