"""检索用索引：中文全文 GIN、向量 HNSW、词典模糊匹配 GIN。

三处都是表达式/部分索引，Django 的 Index 表达不了，用 RunSQL 显式建。
- 全文：chunks.search_text 已存 jieba 分词结果，这里按 simple 配置建表达式索引；
        查询侧必须写成同一个表达式才能命中。
- 向量：只索引非空向量，P1 全表为空也不占空间。
- 词典：term 走 pg_trgm，供错字与简称模糊匹配。
"""

from django.db import migrations

SQL_FORWARD = [
    # pg_trgm 供词典模糊匹配；测试库由 migration 建扩展，不能指望 init.sql
    "CREATE EXTENSION IF NOT EXISTS pg_trgm;",
    """
    CREATE INDEX IF NOT EXISTS idx_chunk_search_text_gin
    ON chunks USING gin (to_tsvector('simple', search_text));
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_chunk_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_term_term_trgm
    ON terms USING gin (term gin_trgm_ops);
    """,
]

SQL_REVERSE = [
    "DROP INDEX IF EXISTS idx_term_term_trgm;",
    "DROP INDEX IF EXISTS idx_chunk_embedding_hnsw;",
    "DROP INDEX IF EXISTS idx_chunk_search_text_gin;",
]


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(SQL_FORWARD, SQL_REVERSE),
    ]
