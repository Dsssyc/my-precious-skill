# My Precious Skill

[English](README.md) | 简体中文

`my-precious-skill` 是一组通用 agent session memory skills 的开发仓库。

- `setup-my-precious`：初始化或连接私有记忆归档仓库。
- `update-my-precious`：扫描新的 source records，并写入新的记忆条目。
- `using-my-precious`：检索已有私有记忆归档仓库。
- 分层的 global、domain 和 project memory nodes 支持继续下钻到 session、
  evidence 和 source anchors。

这个仓库不保存真实历史会话，不运行真实归档定时任务，也不直接 push 私有记忆数据。它只保存可复用的 skill、检索脚本、归档格式约定、部署仓库模板和合成测试。

## 它解决什么问题

当未来的 agent 任务依赖这些历史上下文时：

- 之前的对话
- 过去的 agent 工作
- 历史实现决策
- 尚未完成的后续任务
- 用户偏好和项目约定
- 旧的调试上下文

agent 可以先用 `$using-my-precious` 搜索私有 session memory archive，而不是凭模糊上下文猜测。如果还没有归档仓库，先用 `$setup-my-precious` 初始化。需要立刻捕获新记录时，用 `$update-my-precious`。

## 设计

`setup-my-precious` 是 setup-path skill。它会询问归档仓库应该如何存储，初始化本地归档文件夹，并在用户需要时连接到私有 Git 托管仓库。

`update-my-precious` 是 write-path skill。它扫描 source record 目录，以当前项目路径作为项目 scope，写入该项目最后归档时间之后的新记录；如果已归档过的同一个 source record 的 hash 发生变化，也会刷新该记录。

`using-my-precious` 是 read-path skill。它只要求部署仓库提供稳定的 Markdown summaries 和 JSONL indexes。

这个仓库提供通用 setup、update、search、安全 Git sync 和 scheduler-template 工具。特定来源的采集 adapter、凭证、已启用的定时任务和私有生成数据，仍然应该放在私有部署仓库或可选 adapter 中。

## 仓库结构

```text
my-precious-skill/
  AGENTS.md
  README.md
  README.zh-CN.md
  docs/
    design.md
  benchmarks/
    e2e_induction_recall_benchmark.py
    updater_induction_benchmark.py
    layered_recall_benchmark.py
    cases/
    quality-gates/
  skills/
    setup-my-precious/
      SKILL.md
      agents/openai.yaml
      assets/agent-memory-repo/
      scripts/setup_memory_archive.py
    update-my-precious/
      SKILL.md
      agents/openai.yaml
      scripts/update_memory_archive.py
    using-my-precious/
      SKILL.md
      agents/openai.yaml
      references/archive-format.md
      scripts/search_memory.py
  templates/
    agent-memory-repo/
      AGENTS.md
      INDEX.md
      README.md
      .gitignore
      config/
      memories/
      index/
      daily/
      sessions/
      prompts/summarize_session.prompt.md
      schemas/memory_node.schema.json
      schemas/session_summary.schema.json
      tools/search_memory.py
      tools/update_memory_archive.py
      tools/run_memory_updates.py
      tools/audit_memory_archive.py
      tools/backfill_memory_archive.py
      tools/render_scheduler.py
      tools/sync_memory_archive.py
  tests/
    test_audit_memory_archive.py
    test_search_memory.py
    test_run_memory_updates.py
    test_setup_memory_archive.py
    test_sync_memory_archive.py
    test_update_memory_archive.py
```

## 把这个仓库交给 agent

把这个 GitHub 仓库地址交给支持 skill 仓库的 agent：

```text
https://github.com/Dsssyc/my-precious-skill
```

这个仓库在 `skills/` 下提供 `setup-my-precious`、`update-my-precious`
和 `using-my-precious`。具备 skill repository 支持的 agent 或 installer
可以从仓库地址发现它们。

## 使用 skill

初始化归档仓库：

```text
$setup-my-precious 创建一个本地私有记忆归档仓库
```

```text
$setup-my-precious 为我的记忆归档创建一个私有 Git 托管仓库
```

立刻更新归档仓库：

```text
$update-my-precious 扫描当前项目的新 session records 并更新记忆
```

```text
$update-my-precious 从 /path/to/session-records 为当前项目归档新记录
```

检索归档仓库：

```text
$using-my-precious 查找之前关于迁移策略的历史决策
```

```text
$using-my-precious 根据我的历史 agent memory，找一下之前为什么不建议默认上传 raw transcript
```

```text
$using-my-precious 查找之前关于生产事故排查的上下文
```

`$setup-my-precious` 默认会把 archive 位置写入
`~/.config/my-precious/config.json`。环境变量只是当前 shell 和自动化任务的
override，不应该是主要 setup 机制。
在平台支持的情况下，config 文件会用私有文件权限写入。

工具会按以下顺序寻找私有部署仓库：

1. 显式命令参数，例如 `--repo` 或 `--memory-repo`
2. 当脚本从部署仓库内运行时，使用同仓库位置
3. `AGENT_SESSION_MEMORY_REPO`
4. `AGENT_MEMORY_REPO`
5. `MY_PRECIOUS_CONFIG` 或 `AGENT_SESSION_MEMORY_CONFIG`
6. `~/.config/my-precious/config.json`
7. `~/repos/agent-memory`

可选的当前 shell override：

```bash
export AGENT_SESSION_MEMORY_REPO="$HOME/repos/agent-memory"
```

## 创建私有部署仓库

推荐路径是让 `$setup-my-precious` 询问存储方式并自动初始化仓库。也可以手动设置：

复制模板到另一个私有仓库位置：

```bash
REPO="/path/to/my-precious-skill"
MEMORY_REPO="$HOME/repos/agent-memory"

mkdir -p "$MEMORY_REPO"
rsync -a "$REPO/templates/agent-memory-repo/" "$MEMORY_REPO/"

cd "$MEMORY_REPO"
git init
```

如果使用私有 Git 托管仓库，用你常用的托管工作流创建并推送这个部署仓库。不要把凭证写入仓库文件、shell 历史、日志或生成的摘要。如果本地 archive 文件夹已经有 Git history，先审查历史再 push；setup helper 默认会拒绝发布已有历史，除非显式传入 `--allow-existing-history`。

部署仓库才应该保存真实数据：

```text
agent-memory/
  config/projects.jsonl
  memories/*.jsonl
  index/memories.jsonl
  index/*.jsonl
  daily/YYYY/YYYY-MM-DD.md
  sessions/YYYY/MM/DD/<session>/summary.md
  sessions/YYYY/MM/DD/<session>/evidence.md
  sessions/YYYY/MM/DD/<session>/meta.json
  sessions/YYYY/MM/DD/<session>/source-map.json
```

## 直接使用部署仓库

从共享 source record 目录执行全域更新：

```bash
python ~/repos/agent-memory/tools/run_memory_updates.py \
  --memory-repo ~/repos/agent-memory \
  --source-dir /path/to/session-records \
  --allow-redacted-secrets
```

如果 `config/projects.jsonl` 是空的，runner 会扫描 source records，读取
`cwd`、`project_path` 等项目元数据，自动注册发现到的项目，然后更新每个
enabled project。

如果需要有意修复历史摘要，给 runner 加 `--rewrite-existing`。这个模式会重建
匹配的 source records，并替换同一 project/source record 的旧归档条目；它不是
常规增量路径。

对于 archive 中已经存在的历史条目，优先使用基于 meta 的 backfill 工具：

```bash
python ~/repos/agent-memory/tools/backfill_memory_archive.py \
  --memory-repo ~/repos/agent-memory \
  --allow-redacted-secrets
```

`--allow-redacted-secrets` 会保持 secret 检测开启，但允许在识别出的 secret
pattern 已脱敏后写入 archive。若需要人工先审查疑似 secret 的 source record，
则不要加这个参数。

从 source record 目录更新记忆：

```bash
python ~/repos/agent-memory/tools/update_memory_archive.py \
  --memory-repo ~/repos/agent-memory \
  --source-dir /path/to/session-records \
  --project-path /path/to/project
```

如果 source record 目录混有多个项目的记录，要求记录显式带有项目元数据：

```bash
python ~/repos/agent-memory/tools/update_memory_archive.py \
  --source-dir /path/to/session-records \
  --project-path /path/to/project \
  --require-project-metadata
```

审计生成的 archive 质量：

```bash
python ~/repos/agent-memory/tools/audit_memory_archive.py \
  --memory-repo ~/repos/agent-memory
```

audit 会检查生成文本质量、不安全 key-like value、memory node 下钻路径，以及
evidence `quote_id` 是否可达。

生成 aggregate-safe 的 natural induction review decision skeleton：

```bash
python ~/repos/agent-memory/tools/author_induction_review_decisions.py \
  --memory-repo ~/repos/agent-memory \
  --dry-run
```

推荐流程是：先用 `--dry-run` 生成 skeleton 聚合报告，再用 `--write` 只追加缺失的
skeleton rows，由 reviewer 在私有
`reviews/induction_review_decisions.jsonl` 中填写 action，然后运行
`apply_memory_review_decisions.py --dry-run`，最后再 `--write` 应用。skeleton row
只包含 `candidate_id`、`candidate_text_sha256` 和 `candidate_fingerprint`；
authoring report 只输出聚合 JSON，不打印 candidate text、memory text、source
path、query、raw ref 或 transcript。这只是私有部署仓库的安全 authoring helper，
不是人工审批 UI，也不是本开发仓库里的 generated private archive data。

预览或应用 lifecycle review decisions，且不渲染私有 memory text：

```bash
python ~/repos/agent-memory/tools/apply_memory_review_decisions.py \
  --memory-repo ~/repos/agent-memory \
  --dry-run
```

review decisions 保存在私有部署仓库的
`reviews/memory_lifecycle_decisions.jsonl`。dry-run report 只输出聚合 JSON，
包括 decision count、applied/ignored action count，以及应用前后的 lifecycle
relation count。只有在 review decision 文件已经过审查后才使用 `--write`；
它会重建 archive indexes 并应用已确认的 lifecycle relations。

运行 privacy-safe shadow evaluation，不把私有 source records 复制进这个开发仓库：

```bash
python ~/repos/agent-memory/tools/shadow_eval_memory_archive.py \
  --repo ~/repos/agent-memory \
  --cases /path/to/redacted_probe_cases.jsonl \
  --audit-script ~/repos/agent-memory/tools/audit_memory_archive.py \
  --fail-under memory_recall_at_5=1.0 \
  --fail-over top_k_noise_at_5=0.25
```

shadow report 只输出聚合 JSON。probe case 可以使用旧的
`expected_memory_id`，也可以使用 `expected_memory_ids` 表示一个 query
有多个可接受的 memory-node answer。`expected_layer` 是 soft preferred
layer；`expected_not_memory_id` 用于检查 active-memory suppression；
`forbidden_output_patterns` 是不得出现在 audit/search 输出中的私有或
secret-like 正则。`expected_abstain: true` case 只有在没有返回 memory hit
时才算通过；report 会输出 abstain pass rate 和 abstain false-positive
result count。JSON report 还会输出 privacy-safe `diagnostics` block，按
`recall_miss`、`abstain_false_positive`、`suppression_failure`、
`privacy_failure` 和 `top_k_noise` 聚合失败 case。diagnostic entry 只包含
case ordinal、短 case-label hash、计数和 noise bucket，不渲染 probe query、
memory ID、source path、raw ref 或 forbidden pattern。`--fail-under`、
`--fail-over`、`--fail-under-file` 和
`--fail-over-file` 可以约束数值聚合指标或 dotted metric path，例如
`metrics.provenance_coverage.score`。threshold failure 只输出 metric 名称、
实际值和阈值，不输出 JSON report。shadow eval 不渲染 memory text、evidence
text、source paths、raw anchors、returned memory IDs、queries 或
forbidden-pattern text；非法 `forbidden_output_patterns` 正则也不会回显原始
pattern。

不用 agent，也可以直接运行搜索脚本：

```bash
python ~/repos/agent-memory/tools/search_memory.py "private session archive"
```

当 `index/memories.jsonl` 存在时，搜索会先从分层 memory nodes 开始。
使用 depth 控制继续下钻到支持它的 sessions、evidence 或受保护的 source
refs。source depth 默认只输出 `source_ref_id`、`status` 和 `reason`，不会打印
raw source content；不安全的 source ref 会显示为 `[unsafe-source-ref]`，不安全的
metadata 字段会显示为 `[unsafe-field]`。
带有已确认 `superseded_by`、`contradicted_by` 或 `deprecated_by` lifecycle
links 的 memory node 会被视为非活跃记忆，并被搜索跳过；deprecation marker
nodes 默认也会被跳过。
只有用户明确要求 source reachability 时，才使用 `--depth source`：

```bash
python ~/repos/agent-memory/tools/search_memory.py "private session archive" --depth session
python ~/repos/agent-memory/tools/search_memory.py "private session archive" --depth evidence
python ~/repos/agent-memory/tools/search_memory.py "private session archive" --depth source
```

只有用户明确要求 raw-source 检查时，才请求短的脱敏预览：

```bash
python ~/repos/agent-memory/tools/search_memory.py "private session archive" --depth source --raw-source-preview all
```

指定仓库路径：

```bash
python templates/agent-memory-repo/tools/search_memory.py \
  "access control decision" \
  --repo ~/repos/agent-memory
```

搜索 evidence：

```bash
python ~/repos/agent-memory/tools/search_memory.py \
  "raw transcript upload" \
  --include-evidence
```

为当前项目提高相关记录排序，同时保留跨项目命中：

```bash
python ~/repos/agent-memory/tools/search_memory.py \
  "FastDB lifetime boundary" \
  --project-path /path/to/current/project
```

搜索脚本使用无依赖的 hybrid lexical 排序，覆盖 JSONL 索引、summary 文件和
可选 evidence 文件。排序会提高 decision、reusable facts、unresolved tasks、
summary、user intent 等高信号字段的权重，奖励精确短语和重要 literal token，
并输出 `why:` 行，帮助 agent 判断命中来自结构化字段、短语匹配、重要 token
覆盖，还是当前项目上下文。

### 分层召回 Benchmark

可以用合成 case 检查分层召回：

```bash
python benchmarks/layered_recall_benchmark.py \
  --repo /path/to/agent-memory \
  --cases /path/to/cases.jsonl \
  --search-script templates/agent-memory-repo/tools/search_memory.py
```

这个 harness 会输出受 LongMemEval、LOCoMo、Memora、RULER 风格检索压力测试
启发的长期记忆可靠性指标：

- `memory_recall_at_1`、`memory_recall_at_5`、`memory_mrr`、
  `memory_ndcg_at_5`、`memory_precision_at_5` 和
  `memory_micro_precision_at_5`，以及用于 top-k 噪声的
  `memory_noise_count_at_5` 和 `top_k_noise_at_5`
- `memory_explainability` 和 `memory_explainability_cases`，用于检查排到前面的
  expected memory 是否有高信号 `why:` 原因，而不是只靠宽泛或低信号匹配
- `layer_calibration` 和 `layer_calibration_cases`，用于检查声明了
  `expected_layer` 的 case 是否从指定的 `global`、`domain` 或 `project` 层召回
- `layer_path_success_rate`，要求 top-5 memory recall、支撑 summary path，以及
  已配置的 expected layer 同时对齐
- `scope_filter_recall` 和 `scope_filter_cases`，用于验证这些分层 case 在使用
  `--scope <expected_layer>` 检索时仍能召回 expected memory
- `wrong_scope_suppression` 和 `wrong_scope_suppression_cases`，用于验证 scoped
  search 不会从其它层返回这个 expected memory
- rank 分布字段：`memory_ranked_cases`、`memory_rank_missing_cases`、
  `memory_rank_mean`、`memory_rank_median` 和 `memory_rank_histogram`
- `session_drilldown_at_5`、`drilldown_success_rate`、`source_reachability`、
  `source_ref_reachability`、
  `source_depth_policy_pass_rate`、`raw_preview_redaction_pass_rate`、
  `source_drilldown_privacy_pass_rate`、`evidence_reachability`，以及带
  `evidence_text_cases` 的 `evidence_text_reachability`
- `answer_reachability`、`answer_normalized_reachability` 和
  `answer_token_f1`，用于检查召回的 memory/session/source 输出里是否出现
  `reference_answer` 片段
- `abstention_accuracy`、`negative_memory_suppression`、
  `stale_memory_suppression`、`update_consistency`、
  `lifecycle_supersession_cases`、`lifecycle_supersession_reciprocity`，以及
  aggregate `suppression_pass_rate`
- `privacy_boundary_pass_rate`、`privacy_leak_count`、总 `latency_ms`、`latency_mean_ms`、
  `latency_max_ms`、分母计数字段，以及按 `category` 分组的汇总

正向 JSONL case 必须包含 `query`、`expected_memory_id`、
`expected_summary_path` 和 `expected_source_anchor`。可选字段包括
`case_id`、`category`、`source_benchmark`、`reference_answer`、
`reference_evidence`、`required_evidence_paths`、`expected_not_memory_id`、
`stale_memory_id`、`temporal_scope`、`expected_layer` 和
`forbidden_output_patterns`。
packaged synthetic suite 包含显式 `broad_lexical_noise` 拒答 case，用来把宽泛词面
重叠噪声和普通拒答分开计量。
`forbidden_output_patterns` 的每一项都是 Python 正则表达式，会匹配合并后的
memory、session、source 和显式 raw preview 输出。
即使 case 未配置显式 forbidden pattern，`privacy_leak_count` 也会把通用
secret-like 输出标识计为泄漏。
拒答 case 设置 `expected_abstain` 为 `true`，不需要正向 expected 字段。
`answer_reachability` 检查精确 reference answer 文本可达性；
`answer_normalized_reachability` 忽略大小写和标点；`answer_token_f1`
报告最佳连续窗口 token overlap。这些都是检索侧检查，不是生成答案的语义评分。
`evidence_text_reachability` 检查 required evidence 文件里是否包含精确
`reference_evidence` 片段，避免只验证 evidence path 而没有验证证据文本可达。

可以把仓库外本地下载的公开 benchmark 文件转换成这套 case schema，而不用提交原始
数据：

```bash
python benchmarks/convert_public_memory_benchmark.py \
  --source longmemeval \
  --input /path/outside/repo/longmemeval.json \
  --output /tmp/longmemeval-cases.jsonl

python benchmarks/convert_public_memory_benchmark.py \
  --source locomo \
  --input /path/outside/repo/locomo.json \
  --output /tmp/locomo-cases.jsonl

python benchmarks/convert_public_memory_benchmark.py \
  --source memora \
  --input /path/outside/repo/memora-evaluation.json \
  --output /tmp/memora-cases.jsonl
```

converter 支持官方
[LongMemEval](https://github.com/xiaowu0162/longmemeval)、
[LoCoMo](https://github.com/snap-research/locomo) 和
[Memora](https://github.com/geniesinc/Memora) 发布使用的 schema 形态。它会生成
确定性的 external memory ID 和受保护 source anchor，用于本地评估；不会下载、
vendoring 或提交公开 benchmark 原始记录。

仓库还内置了一份受公开 benchmark 能力维度启发的合成 case suite：

```bash
benchmarks/cases/layered_recall_synthetic.jsonl
```

如果要生成一份量化 synthetic 分数报告，先构建临时合成 archive，再用真实搜索脚本
跑 benchmark：

```bash
python benchmarks/build_synthetic_recall_archive.py \
  --repo /tmp/my-precious-synthetic-archive \
  --cases benchmarks/cases/layered_recall_synthetic.jsonl \
  --include-superseded-distractors

python benchmarks/layered_recall_benchmark.py \
  --repo /tmp/my-precious-synthetic-archive \
  --cases benchmarks/cases/layered_recall_synthetic.jsonl \
  --search-script templates/agent-memory-repo/tools/search_memory.py \
  --details-jsonl /tmp/my-precious-synthetic-details.jsonl \
  --failures-json /tmp/my-precious-synthetic-failures.json \
  --fail-under-file benchmarks/quality-gates/layered_recall_synthetic.json \
  --fail-over-file benchmarks/quality-gates/layered_recall_synthetic_max.json
```

`--details-jsonl` 会为每条 case 写一行 JSON，包含 rank、drill-down、source、
evidence、拒答、stale suppression、lifecycle supersession、source-depth policy
和 privacy 结果。
疑似敏感或包含控制字符的 returned identifier 会写成 `[unsafe-result-identifier]`。
`--failures-json`
会写结构化质量门禁失败信息，包括 metric、value、threshold，以及安全的失败
case 摘要：case ID、行号、category、source benchmark、失败检查名、memory rank、
recall 标志、session drilldown 状态和 source reachability 状态；它仍然不会写原始
query、expected memory ID、raw source path、reference answer 或返回片段。`--fail-under` 会保留
stdout 的 aggregate JSON，并在数值指标低于阈值时用非零状态退出，方便在 CI
里作为质量门禁；`--fail-over-file` 可用于 `failed_case_count`、
`memory_rank_missing_cases`、rank mean/median 等上界门禁。阈值必须是有限数值；
NaN 和 Infinity 会在比较前被拒绝。
packaged `benchmarks/quality-gates/layered_recall_synthetic.json` 同时覆盖
source/evidence path、source-depth governance、evidence-text、answer
reachability、拒答、broad lexical noise resistance、stale/update、lifecycle
reciprocity、layer path/drilldown success、suppression、privacy、rank 和分母计数。
memory/session/source 每一层搜索 subprocess 默认有 30 秒超时；`--search-timeout-s`
必须是有限正数，可以在 CI smoke test 中调低，或在大型本地 archive 上调高。

上面的 packaged quality-gate 命令默认加入 superseded distractor node，让
`lifecycle_supersession_cases` 有非零分母。如果要手动给 stale-memory
suppression 增加压力，也可以在构建临时 archive 时加同一个选项：

```bash
python benchmarks/build_synthetic_recall_archive.py \
  --repo /tmp/my-precious-synthetic-archive \
  --cases benchmarks/cases/layered_recall_synthetic.jsonl \
  --include-superseded-distractors
```

这些 case 只是合成模板，不包含私有记忆数据，也没有复制公开 benchmark 原始记录。
如果需要跑外部公开 benchmark，应把下载数据保存在仓库外，并在本地转换为同一套
JSONL case schema。这个 benchmark 面向 My Precious 的分层召回，不应该直接
等同于使用原文 transcript embedding 的系统分数。

仓库也内置了一份 updater-driven synthetic induction benchmark。它和 layered
recall benchmark 的区别是：它不会预构造 `memories/*.jsonl`，而是创建临时合成
source records，运行 `setup_memory_archive.py`，再运行部署模板里的
`tools/update_memory_archive.py`，最后评分生成出来的 archive：

```bash
python benchmarks/updater_induction_benchmark.py \
  --cases benchmarks/cases/updater_induction_synthetic.jsonl \
  --fail-under-file benchmarks/quality-gates/updater_induction_synthetic.json \
  --fail-over-file benchmarks/quality-gates/updater_induction_synthetic_max.json
```

induction benchmark 只输出 aggregate JSON 指标：
`induction_success_rate`、`natural_induction_success_rate`、
`natural_false_promotion_rate`、`auto_promotion_precision`、
`cross_project_generalization_rate`、`project_scope_precision`、
`ambiguous_candidate_review_rate`、`induction_review_routing_rate`、
`induction_review_decision_apply_rate`、
`induction_review_approve_promotion_rate`、
`induction_review_ignore_suppression_rate`、
`low_confidence_review_rate`、`scope_change_review_rate`、
`conflict_review_rate`、
`review_routing_rate`、`process_noise_rejection_rate`、
`ephemeral_status_rejection_rate`、`hypothetical_rejection_rate`、
`acknowledgement_only_rejection_rate`、
`temporary_local_decision_rejection_rate`、`generic_rule_rejection_rate`、
`evidence_retention_rate`、`source_ref_policy_pass_rate`、
`lifecycle_link_accuracy`、`forced_memory_capture_rate`、
`privacy_refusal_pass_rate`、`privacy_redaction_pass_rate` 和
`privacy_leak_count`。packaged synthetic suite 覆盖跨项目自动归纳、项目作用域归纳、
自然语言 preference/workflow 归纳、project-scoped implementation constraint、
ambiguous scope candidate 进入 review、natural induction review calibration、
adversarial natural-language precision cases、process-noise rejection、
source-record forced memory、supersede/contradict/deprecate lifecycle link、
redacted source record，以及默认拒绝 likely-secret source record。natural review
calibration 覆盖只有部分支持的重复 statement、冲突 preference、scope broadening
或 narrowing、低置信一次性 candidate，以及应该保持 reviewable 而不是被拒绝或
提升的 candidate。review candidate row 会保留 evidence/source refs 供审计使用，
但只存 `candidate_text_sha256`，不渲染 candidate text。synthetic induction
review decisions 使用私有 `reviews/induction_review_decisions.jsonl`，action
为 `approve_promote`、`reject` 或 `noop`；只有 approve decision 会把这些
review candidates 提升为 memory nodes。decision-set validation 会拒绝重复
`decision_id`、重复的完整行，以及同一 candidate 或 candidate fingerprint 上
互相冲突的 action。dry-run 只输出 aggregate duplicate、conflict、stale、
unsafe 和 unknown 计数，不渲染 candidate text、memory text、source path 或
raw refs。aggregate-safe authoring helper 可以为仍 active 的 candidate 追加
pending skeleton rows，同时保留已有人工 decision，并跳过已经 reflected 的
decision；reviewer 仍然需要在 apply preflight/write 前自行填写私有 action。
adversarial precision cases
覆盖带 `should`/`must` 的
一次性 status/progress update、只有 acknowledgement 的回复、`we could` 或 `maybe`
假设语句、临时本地 implementation choice、test-result chatter、quoted prompt-like
text，以及缺少 distinctive support 的宽泛 generic rule。它不会渲染 source content、
memory text、source path、raw ref 或 per-case detail。

end-to-end synthetic benchmark 会把写入路径和读取路径串起来：它创建临时合成
source records，运行真实 `setup_memory_archive.py` 和 updater，从生成的
`index/memories.jsonl` 派生 recall cases，然后用真实 layered recall benchmark
和复制出的 `tools/search_memory.py` 评分：

```bash
python benchmarks/e2e_induction_recall_benchmark.py \
  --cases benchmarks/cases/e2e_induction_recall_synthetic.jsonl \
  --fail-under-file benchmarks/quality-gates/e2e_induction_recall_synthetic.json \
  --fail-over-file benchmarks/quality-gates/e2e_induction_recall_synthetic_max.json
```

它只输出 aggregate e2e 指标：
`natural_induction_success_rate`、`cross_project_generalization_rate`、
`project_scope_precision`、`ambiguous_candidate_review_rate`、
`process_noise_rejection_rate`、`e2e_memory_recall_at_1`、
`e2e_memory_recall_at_5`、
`e2e_layer_assignment_accuracy`、`e2e_session_drilldown_rate`、
`e2e_evidence_reachability_rate`、`e2e_source_policy_pass_rate`、
`e2e_lifecycle_active_suppression_rate`、`e2e_forced_memory_recall_rate`
和 `privacy_leak_count`。packaged suite 覆盖跨项目自动归纳、项目作用域归纳、
自然语言 preference/workflow 归纳、project-scoped implementation constraint、
ambiguous scope candidate 进入 review、process-noise rejection、
source-record forced memory、supersede/contradict/deprecate lifecycle
suppression、redacted source record，以及默认拒绝 likely-secret source
record，并且不渲染私有 case detail。

渲染默认全域 scheduler：

```bash
python ~/repos/agent-memory/tools/render_scheduler.py \
  --memory-repo ~/repos/agent-memory \
  --source-dir /path/to/session-records \
  --backend launchd \
  --schedule daily \
  --output ~/repos/agent-memory/.tmp/agent-memory.plist
```

只有在你想为单个项目单独配置 scheduler 时，才添加
`--project-path /path/to/project`。

渲染 agent-native automation prompt：

```bash
python ~/repos/agent-memory/tools/render_scheduler.py \
  --memory-repo ~/repos/agent-memory \
  --source-dir /path/to/session-records \
  --backend agent-native \
  --allow-redacted-secrets \
  --push-after-update \
  --output ~/repos/agent-memory/.tmp/agent-native-update.txt
```

agent-native automation 应只使用部署仓库作为唯一工作目录。多个工作目录可能会
创建多个并发 automation 对话。

安全提交并 push 生成的 archive 更新：

```bash
python ~/repos/agent-memory/tools/sync_memory_archive.py \
  --memory-repo ~/repos/agent-memory \
  --push
```

sync helper 只 stage archive 路径（`INDEX.md`、`config/projects.jsonl`、
`index/`、`memories/`、`reviews/`、`daily/` 和 `sessions/`）。提交前它会拒绝
tool/script 改动、archive audit findings、未脱敏的 key-like value 和
whitespace 错误。

## 归档格式约定

部署仓库应提供：

- `INDEX.md`：人类和 agent 可读的总览。
- `config/projects.jsonl`：全域 runner 使用的可选项目注册表。
- `memories/global.jsonl`、`memories/domains.jsonl`、
  `memories/projects.jsonl` 和 `memories/explicit.jsonl`：分层 memory nodes。
- `reviews/memory_lifecycle_decisions.jsonl`：针对模糊 lifecycle candidates 的
  私有 reviewer decisions。
- `reviews/induction_review_decisions.jsonl`：针对 natural induction candidates
  的私有 reviewer decisions。重复 ID、重复完整行，以及同一 candidate 或
  fingerprint 上冲突的 action 会被拒绝。
- `index/memories.jsonl`：合并后的分层 memory 搜索索引。
- `index/memory_review_candidates.jsonl`：需要人工 review 的模糊 lifecycle pairs。
- `index/induction_review_candidates.jsonl`：promotion 前需要 review 的
  aggregate-safe natural induction candidates。
- `index/induction_review_decision_results.jsonl`：applied/ignored induction
  review decision 状态，供聚合检查使用。
- `index/memory_review_decision_results.jsonl`：applied/ignored review decision
  状态，供聚合检查使用。
- `index/memory_consolidation_trace.jsonl`：updater 生成的 merge、supersede、
  contradict、deprecate 和 skip 决策说明。
- `index/sessions.jsonl`：每个 session 一行。
- `index/decisions.jsonl`：每个可复用决策一行。
- `index/unresolved.jsonl`：每个未完成任务一行。
- `sessions/YYYY/MM/DD/.../summary.md`：每个 session 的结构化摘要。
- `sessions/YYYY/MM/DD/.../evidence.md`：支持关键结论的短证据片段。

详细格式见：

```text
skills/using-my-precious/references/archive-format.md
```

## 当前已实现

- `setup-my-precious` skill。
- `update-my-precious` skill。
- `using-my-precious` skill。
- skill UI metadata：`agents/openai.yaml`。
- 通用 archive format reference。
- 分层的 global、domain 和 project memory nodes，可下钻到 session、
  evidence 和 source anchors。
- 面向 automatic memory nodes 的轻依赖 semantic consolidation，支持
  paraphrase support merge、false partial-supersession guards、
  contradiction links、deprecation links、partial supersession、retired node
  confidence revision 和 robustness benchmark gates。
- 面向语义 lifecycle 模糊关系的 review queue，以及解释 merge、supersede、
  contradict、deprecate 和 skip 决策的 consolidation trace index。
- aggregate-safe natural induction review candidate index，用于低置信、冲突或
  scope-changing 的 natural candidates，避免自动提升。
- aggregate-safe induction review decision results，用于 synthetic approve、
  reject、noop、duplicate、conflict、stale、unsafe 和 unknown calibration。
- 只输出聚合结果的 review-decision dry-run/apply 工具，可把已确认的
  lifecycle review decisions 转成 reciprocal memory links。
- privacy-safe real-archive shadow evaluation runner，可输出聚合 recall、
  suppression、lifecycle、top-k noise、noise-source、provenance 和 numeric
  quality gate 指标；legacy
  archive 也可生成结构报告，但在没有 `index/memories.jsonl` 前 memory top-k
  指标会保持为 `null`。报告不渲染 memory text、evidence text、source paths 或
  raw anchors。
- end-to-end synthetic induction-to-recall benchmark，可运行 setup、updater、
  生成后的 layered recall cases，以及复制出的 search script，并只输出
  aggregate quality gate 指标。
- updater-driven natural-induction precision gates，覆盖 adversarial synthetic
  false-promotion cases 和 review routing，并包含 low-confidence、scope-change
  和 conflict candidates 的 induction-review routing rate。
- 零依赖 hybrid lexical 搜索脚本，支持字段加权、短语覆盖、可选项目上下文
  boost、低信号 memory-node 过滤和可解释结果原因。
- 基于项目路径和 source/session timestamp 的增量 update 脚本。
- searchable summary、短 evidence snippet、source-map、daily summary 和 JSONL index 生成。
- 默认拒绝疑似 secret source records 的安全检查。
- 面向共享 source record 目录的可选 project metadata 强制检查。
- 可从 source records 自举空项目注册表的全域 update runner。
- 有意重写既有 source-record entries 的 backfill 模式。
- 可按已有 archive metadata 修复历史条目、避免重复全量扫描 source 目录的 backfill 工具。
- 检查 wrapper-field noise、process-update text 和 key-like values 的 archive audit 工具。
- 面向 launchd 和 cron 格式的 reviewable scheduler template generator。
- 带单一工作目录要求的 agent-native automation prompt 渲染。
- 面向生成 archive 更新的安全 Git sync helper。
- 私有部署仓库模板。
- setup、update、global-runner 和 search 的合成测试。

## 职责归属

这个开发仓库应该提供可复用、非私有的构建块：

- skills 及其 bundled scripts/assets。
- 归档格式约定和 schemas。
- 部署仓库模板。
- 通用搜索工具。
- 可复用 setup helpers。
- 可复用的归档流水线组件，例如 redaction、rendering、indexing、validation、global update running、安全 Git sync、scheduler-template generation 和 source-adapter interfaces。

`$setup-my-precious` 被触发后，应该在询问用户后执行这些运行期 setup 动作：

- 选择 local-only storage 或 Git-backed storage。
- 选择或创建本地归档目录。
- 需要时创建/连接私有 Git 托管仓库。
- 复制部署模板。
- 需要时初始化 Git。
- 把 archive 位置写入 `~/.config/my-precious/config.json`。
- 告诉用户可选的 `AGENT_SESSION_MEMORY_REPO` 当前 shell override。
- 在部署仓库已有具体 archive 和 sync command 之后，可选配置 recurring archive job。

私有部署仓库应该保存用户相关状态和运行期操作：

- 生成的 `sessions/`、`daily/` 和 `index/` 数据。
- `config/projects.jsonl` 中的项目注册状态。
- 项目级 high-water marks 和 source-record hash freshness 状态。
- 本地配置和日志。
- 配置好的 remotes。
- 已启用的定时任务或 scheduler config。
- 特定来源的 ingestion settings。

部署仓库不应该提交 raw transcripts、credentials、cookies、private keys 或未脱敏数据。

属于 `$setup-my-precious` 运行期 setup 的工作：

- 询问用户 storage mode 和 path。
- 需要时询问 Git 托管仓库名。
- 创建/连接私有仓库。
- 在 archive command 存在后询问是否渲染并配置定时任务。
- 验证最终 search command 可运行。

## 验证

先用你的 runtime 对应的 skill validator 校验 skill，然后运行仓库测试：

```bash
python3 -m unittest discover -s tests -p 'test_*.py'

python3 -m py_compile \
  benchmarks/e2e_induction_recall_benchmark.py \
  benchmarks/updater_induction_benchmark.py \
  benchmarks/layered_recall_benchmark.py \
  benchmarks/build_synthetic_recall_archive.py \
  benchmarks/convert_public_memory_benchmark.py \
  skills/setup-my-precious/scripts/setup_memory_archive.py \
  skills/update-my-precious/scripts/update_memory_archive.py \
  skills/update-my-precious/scripts/memory_consolidation.py \
  skills/using-my-precious/scripts/search_memory.py \
  templates/agent-memory-repo/tools/run_memory_updates.py \
  templates/agent-memory-repo/tools/audit_memory_archive.py \
  templates/agent-memory-repo/tools/backfill_memory_archive.py \
  templates/agent-memory-repo/tools/update_memory_archive.py \
  templates/agent-memory-repo/tools/memory_consolidation.py \
  templates/agent-memory-repo/tools/search_memory.py \
  templates/agent-memory-repo/tools/render_scheduler.py \
  templates/agent-memory-repo/tools/sync_memory_archive.py
```

## 安全边界

- 不默认上传 raw transcript。
- 不把 token、cookie、private key、`.env` 写进仓库。
- 当前仓库只放通用工具和合成测试。
- 真实 memory repo 应保持 private。
- 检索时优先读 summary；只有证据不足时才读 evidence。
