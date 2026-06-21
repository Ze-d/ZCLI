# Teammate 完成后仍显示 working

## 现象

创建一次性 reviewer，让它检查 `seed.txt`：

```text
zcli (test-start) >> 请调用 spawn_teammate 创建 alice，角色 reviewer，让她检查 seed.txt 是否已排序。
[spawn_teammate] Teammate 'alice' spawned as reviewer
```

Lead 随后能够收到 alice 的 completion 消息，但 `/team` 仍显示：

```text
alice: role=reviewer status=working
```

表面上看，Teammate 完成工作后没有退出 `working` 状态。

## 本次实际根因

状态回写本身没有失败。旧版后台循环的执行顺序是：

```text
执行初始 Prompt
  → 发送 completion 给 Lead
  → status = idle
  → 立即扫描整个 TaskStore
  → 自动认领第一个可执行的 pending Task
  → status = working
```

端到端测试此前创建了 `worktree smoke` 等持久 Task。alice 完成 `seed.txt` 检查并短暂进入 `idle` 后，立即认领了其中一个遗留 Task，因而再次变成 `working`。

Lead 收到 completion 只能证明初始 Prompt 已完成，不代表 Teammate 后台线程已经结束。由于 `idle → working` 的转换很快，用户通常观察不到中间的 idle 状态，于是误以为状态一直没有更新。

根本问题是自动认领没有显式开关：一次性 reviewer 和持续消费 Task Graph 的 worker 使用了完全相同的行为。不同端到端场景共享 `.zcli/tasks/` 后，这还会造成测试之间相互干扰。

## 修复方案

为 `spawn_teammate` 增加可选参数 `autoClaim`，默认关闭：

```text
spawn_teammate(name, role, prompt, autoClaim=false)
```

修复后的行为：

- `autoClaim=false`：完成初始工作后进入 `idle`，只处理发给自己的消息、计划和关闭请求，不认领无关 Task；
- `autoClaim=true`：空闲时扫描 TaskStore，认领依赖已完成、状态为 pending 且没有 owner 的 Task；
- `/team` 对启用自动认领的成员额外显示 `autoClaim=on`，便于判断 working 的来源；
- Teammate 空闲超过 `idle_timeout` 后仍按原逻辑进入 `completed`。

因此，一次性 reviewer 无需额外参数：

```text
spawn_teammate(name="alice", role="reviewer", prompt="检查 seed.txt 是否已排序")
```

需要持续领取任务的 worker 必须显式启用：

```text
spawn_teammate(name="bob", role="worker", prompt="等待任务", autoClaim=true)
```

## 兼容性与历史数据

这是一次默认行为调整：旧版所有 Teammate 都会自动认领任务，新版只有显式设置 `autoClaim=true` 的成员才会认领。

修复不会改写已经持久化的 Task。旧版成员已经认领的任务仍可能保持 `in_progress` 和原 owner，需要用户根据实际执行结果决定完成、保留或另行处理。正在运行的旧 ZCLI 进程也不会热加载新逻辑，验证前需要退出并重新启动。

## 验证

单元测试覆盖两个互补场景：

1. 默认 reviewer 完成后保持 idle，不认领预先存在的无关 Task；
2. `auto_claim=True` 的 worker 仍可自动认领符合条件的 Task。

```powershell
python -m pytest -q tests/test_teams.py tests/test_tools.py
python -m pytest -q
```

本次修复后的全量结果为 `75 passed`。

端到端验证时，重启 ZCLI 后重新执行 `TEAM-01`。收到 alice 的 completion 后运行 `/team`，应看到 `status=idle`；`TEAM-03` 的自动认领场景则必须显式传入 `autoClaim=true`。
