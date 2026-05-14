# My Precious Skill

[English](README.md) | 简体中文

`my-precious-skill` 是一组通用 agent session memory skills 的开发仓库。

- `setup-my-precious`：初始化或连接私有记忆归档仓库。
- `update-my-precious`：扫描新的 source records，并写入新的记忆条目。
- `using-my-precious`：检索已有私有记忆归档仓库。

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

`update-my-precious` 是 write-path skill。它扫描 source record 目录，以当前项目路径作为 high-water-mark key，只写入该项目最后归档时间之后的新记录。

`using-my-precious` 是 read-path skill。它只要求部署仓库提供稳定的 Markdown summaries 和 JSONL indexes。

这个仓库提供通用 setup、update、search 和 scheduler-template 工具。特定来源的采集 adapter 和仓库同步，仍然应该放在私有部署仓库或可选 adapter 中。

## 仓库结构

```text
my-precious-skill/
  README.md
  README.zh-CN.md
  docs/
    design.md
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
      index/
      daily/
      sessions/
      prompts/summarize_session.prompt.md
      schemas/session_summary.schema.json
      tools/search_memory.py
      tools/update_memory_archive.py
      tools/render_scheduler.py
  tests/
    test_search_memory.py
    test_setup_memory_archive.py
    test_update_memory_archive.py
```

## 安装 skill

选择兼容 agent runtime 的 user-level skills 目录，然后把三个 skill 文件夹复制进去：

```bash
REPO="/path/to/my-precious-skill"
SKILLS_DIR="/path/to/agent/skills"

mkdir -p "$SKILLS_DIR"
rsync -a --delete \
  "$REPO/skills/setup-my-precious/" \
  "$SKILLS_DIR/setup-my-precious/"
rsync -a --delete \
  "$REPO/skills/update-my-precious/" \
  "$SKILLS_DIR/update-my-precious/"
rsync -a --delete \
  "$REPO/skills/using-my-precious/" \
  "$SKILLS_DIR/using-my-precious/"
```

安装后重启当前 agent session，让 runtime 重新发现 skill。

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

skill 会按以下顺序寻找私有部署仓库：

1. `AGENT_SESSION_MEMORY_REPO`
2. `AGENT_MEMORY_REPO`
3. `~/repos/agent-memory`

推荐在 shell 配置中固定：

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

如果使用私有 Git 托管仓库，用你常用的托管工作流创建并推送这个部署仓库。不要把凭证写入仓库文件、shell 历史、日志或生成的摘要。

部署仓库才应该保存真实数据：

```text
agent-memory/
  index/*.jsonl
  daily/YYYY/YYYY-MM-DD.md
  sessions/YYYY/MM/DD/<session>/summary.md
  sessions/YYYY/MM/DD/<session>/evidence.md
  sessions/YYYY/MM/DD/<session>/meta.json
  sessions/YYYY/MM/DD/<session>/source-map.json
```

## 直接使用部署仓库

从 source record 目录更新记忆：

```bash
python ~/repos/agent-memory/tools/update_memory_archive.py \
  --memory-repo ~/repos/agent-memory \
  --source-dir /path/to/session-records \
  --project-path /path/to/project
```

不用 agent，也可以直接运行搜索脚本：

```bash
python ~/repos/agent-memory/tools/search_memory.py "private session archive"
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

## 归档格式约定

部署仓库应提供：

- `INDEX.md`：人类和 agent 可读的总览。
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
- 零依赖搜索脚本。
- 基于项目路径和 source/session timestamp 的增量 update 脚本。
- searchable summary、短 evidence snippet、source-map、daily summary 和 JSONL index 生成。
- 默认拒绝疑似 secret source records 的安全检查。
- 面向 launchd 和 cron 格式的 reviewable scheduler template generator。
- 私有部署仓库模板。
- setup、update 和 search 的合成测试。

## 职责归属

这个开发仓库应该提供可复用、非私有的构建块：

- skills 及其 bundled scripts/assets。
- 归档格式约定和 schemas。
- 部署仓库模板。
- 通用搜索工具。
- 可复用 setup helpers。
- 可复用的归档流水线组件，例如 redaction、rendering、indexing、validation、scheduler-template generation 和 source-adapter interfaces。

`$setup-my-precious` 被触发后，应该在询问用户后执行这些运行期 setup 动作：

- 选择 local-only storage 或 Git-backed storage。
- 选择或创建本地归档目录。
- 需要时创建/连接私有 Git 托管仓库。
- 复制部署模板。
- 需要时初始化 Git。
- 告诉用户应导出的 `AGENT_SESSION_MEMORY_REPO` 值。
- 在部署仓库已有具体 archive command 之后，可选配置 recurring archive job。

私有部署仓库应该保存用户相关状态和运行期操作：

- 生成的 `sessions/`、`daily/` 和 `index/` 数据。
- 从已归档 session timestamps 派生出的项目级 high-water marks。
- 本地配置和日志。
- 配置好的 remotes。
- 已启用的定时任务或 scheduler config。
- 特定来源的 ingestion settings。

部署仓库不应该提交 raw transcripts、credentials、cookies、private keys 或未脱敏数据。

## 可选扩展

后续可在这个基础上继续增强：

- 更多 redaction patterns 和 fixtures。
- archive validation utility。
- source-specific summarizer adapters。

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
  skills/setup-my-precious/scripts/setup_memory_archive.py \
  skills/update-my-precious/scripts/update_memory_archive.py \
  skills/using-my-precious/scripts/search_memory.py \
  templates/agent-memory-repo/tools/update_memory_archive.py \
  templates/agent-memory-repo/tools/search_memory.py \
  templates/agent-memory-repo/tools/render_scheduler.py
```

## 安全边界

- 不默认上传 raw transcript。
- 不把 token、cookie、private key、`.env` 写进仓库。
- 当前仓库只放通用工具和合成测试。
- 真实 memory repo 应保持 private。
- 检索时优先读 summary；只有证据不足时才读 evidence。
