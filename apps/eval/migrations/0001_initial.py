from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Feedback",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("user_key", models.CharField(db_index=True, max_length=64)),
                ("conversation_id", models.CharField(blank=True, default="", max_length=36)),
                ("trace_id", models.CharField(blank=True, default="", max_length=64)),
                ("question", models.CharField(max_length=200)),
                ("answer_excerpt", models.CharField(blank=True, default="", max_length=500)),
                (
                    "rating",
                    models.CharField(
                        choices=[("up", "有用"), ("down", "没用")], max_length=8
                    ),
                ),
                (
                    "reason",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("wrong_fact", "口径/数字错"),
                            ("incomplete", "答不全"),
                            ("off_topic", "答非所问"),
                            ("outdated", "信息过期"),
                            ("other", "其他"),
                        ],
                        default="",
                        max_length=16,
                    ),
                ),
                (
                    "expect",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("answer", "应可答"),
                            ("refuse", "应拒答"),
                            ("unsure", "说不清"),
                        ],
                        default="unsure",
                        max_length=8,
                    ),
                ),
                ("note", models.CharField(blank=True, default="", max_length=200)),
                ("reviewed", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "feedback",
                "ordering": ["-id"],
            },
        ),
        migrations.CreateModel(
            name="EvalRun",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[("eval", "批量回归"), ("drill", "降级演练")], max_length=8
                    ),
                ),
                ("label", models.CharField(blank=True, default="", max_length=80)),
                ("samples", models.IntegerField(default=0)),
                ("metrics", models.JSONField(default=dict)),
                ("report_path", models.CharField(blank=True, default="", max_length=300)),
                ("cost", models.DecimalField(decimal_places=6, default=0, max_digits=12)),
                ("duration_ms", models.IntegerField(default=0)),
                ("started_at", models.DateTimeField()),
                ("finished_at", models.DateTimeField()),
            ],
            options={
                "db_table": "eval_runs",
                "ordering": ["-id"],
            },
        ),
        migrations.AddIndex(
            model_name="feedback",
            index=models.Index(
                fields=["rating", "created_at"], name="idx_fb_rating_created"
            ),
        ),
        migrations.AddIndex(
            model_name="feedback",
            index=models.Index(fields=["trace_id"], name="idx_fb_trace"),
        ),
        migrations.AddIndex(
            model_name="evalrun",
            index=models.Index(
                fields=["kind", "finished_at"], name="idx_eval_kind_finished"
            ),
        ),
    ]
