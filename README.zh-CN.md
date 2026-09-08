# My Precious Skill

[English](README.md) | 简体中文

`my-precious-skill` 提供一组可复用、与具体 agent 无关的私有会话记忆 Skill。
它把记忆能力拆分为配置、写入和读取三条路径，并把真实记忆与这个开发仓库严格
分离。

> 本仓库只保存 Skill、工具、模板和合成测试，不得保存真实会话记忆、原始对话、
> 凭据或私有归档运行状态。

## Skills

| Skill | 职责 | 使用场景 |
| --- | --- | --- |
| [`setup-my-precious`](skills/setup-my-precious/SKILL.md) | 配置 | 创建或连接本地、私有 Git 归档，并可选部署本地语义检索环境。 |
| [`update-my-precious`](skills/update-my-precious/SKILL.md) | 写入 | 显式保存事实，或把新的来源记录增量归纳成持久、可检索的记忆。 |
| [`using-my-precious`](skills/using-my-precious/SKILL.md) | 读取 | 找回历史决策、偏好、项目上下文、未完成事项及其证据。 |

## 快速开始

把下面的仓库地址交给兼容的 agent 或 Skill 安装器：

```text
https://github.com/Dsssyc/my-precious-skill
```

然后按顺序使用三个 Skill。

1. 创建或连接私有归档：

   ```text
   $setup-my-precious 创建一个本地私有记忆归档
   ```

   如果需要私有 Git 存储或本地语义检索，可以在同一次配置对话中提出。

2. 写入新记忆：

   ```text
   $update-my-precious 归档当前项目的新会话记录
   ```

3. 找回历史上下文：

   ```text
   $using-my-precious 查找之前关于迁移策略的决策
   ```

配置完成后，私有归档位置默认记录在
`~/.config/my-precious/config.json`。`AGENT_SESSION_MEMORY_REPO` 仍可作为
当前 shell 的临时覆盖。

## 工作原理

1. 来源适配器提供会话或事件记录。
2. 写入路径先脱敏，再提取持久信息，生成摘要、短证据、索引和分层记忆节点。
3. 记忆按 `global`、`domain`、`project` 分层；来源证据和生命周期关系独立于
   排序逻辑保存。
4. 读取路径组合字段加权检索、SQLite FTS5 BM25、中文 trigram 和 RRF；可选的
   本地 provider 再加入全索引向量召回和 cross-encoder 重排。
5. 检索输出机器可读的 context package。agent 只能根据有摘要、证据路径且状态为
   active/current 的受支持记忆作答，否则拒答。

直接查询部署归档的示例：

```bash
python "$AGENT_SESSION_MEMORY_REPO/tools/search_memory.py" \
  "之前关于迁移策略的决策" \
  --retrieval-mode hybrid_v1 \
  --depth evidence \
  --context-json
```

检索设计见 [ADR-001](docs/decisions/ADR-001-hybrid-memory-retrieval.md)，语义环境的
部署与回滚见
[ADR-002](docs/decisions/ADR-002-deploy-semantic-runtime-from-setup-skill.md)。

## 开发仓库与私有归档

本仓库负责可复用实现：

- 可安装的 Skill 和随附脚本
- 私有部署仓库模板
- 归档 schema 与格式约定
- 合成 benchmark 和质量门禁
- 设计决策与聚合评测记录

私有部署仓库负责用户相关的运行状态：

- 生成的 `sessions/`、`daily/`、`memories/` 和 `index/` 数据
- 项目与 source-stream 注册表
- review decision、调度配置和本地状态
- 私有 Git remote 与部署专用适配器

[`templates/agent-memory-repo`](templates/agent-memory-repo) 是部署模板的源版本；
`setup-my-precious` 内置的模板副本必须与它逐字节同步。

## 仓库结构

```text
skills/                         可安装的配置、写入和读取 Skill
templates/agent-memory-repo/    私有部署仓库的源模板
benchmarks/                     合成与只输出聚合结果的质量门禁
tests/                          合成测试
docs/decisions/                 架构决策记录
docs/evaluations/               评测历史与当前能力边界
tools/                          校验与发布工具
```

## 文档导航

- [系统设计](docs/design.md)
- [归档格式约定](skills/using-my-precious/references/archive-format.md)
- [混合检索决策](docs/decisions/ADR-001-hybrid-memory-retrieval.md)
- [语义环境部署决策](docs/decisions/ADR-002-deploy-semantic-runtime-from-setup-skill.md)
- [召回就绪度与已知限制](docs/evaluations/layered-memory-readiness.md)
- [开发与发布规则](AGENTS.md)

各 Skill 文件是运行流程的事实来源；设计文档解释系统为何这样划分，评测文档记录
已经测得的能力和限制。README 不再重复这些内容。

## 开发与验证

发布或创建 release PR 前运行统一质量门禁：

```bash
python3 tools/run_quality_gates.py
```

常用的聚焦检查：

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 tools/validate_skills.py
```

完整验证矩阵和模板同步规则见 [`AGENTS.md`](AGENTS.md)。

## 安全边界

- 在摘要或证据渲染前完成脱敏。
- 默认拒绝疑似包含 secret 的来源记录。
- 证据片段保持简短，原始来源访问必须显式授权。
- 模型、虚拟环境、凭据、日志、调度状态和生成的私有数据都保存在本仓库之外。
- benchmark 通过只代表有边界的工程证据，不代表所有归档和查询表达都具备普适的
  高召回率。
