"""测试基础设施。

扩展由 migration 自己创建（0001 VectorExtension、0002 pg_trgm），这里不再补建。
"""

import pytest


@pytest.fixture(autouse=True)
def _reset_meter():
    """台账缓冲是进程级全局变量，跨用例残留会引发无标记用例的 DB 访问。"""
    from apps.gateway import meter

    meter.reset()
    yield
    meter.reset()


@pytest.fixture(scope="session", autouse=True)
def _warm_jieba():
    """jieba 首次分词要加载词典，提前热身避免首个用例超时。"""
    import jieba

    jieba.lcut("学生证补办流程")
