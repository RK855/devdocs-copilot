# Git 工作流进阶

## 分支模型

常见有主干开发与 Git Flow。主干开发：main 始终可发布，功能在短生命周期分支上开发，通过 PR 合并。Git Flow：main、develop、feature、release、hotfix 多分支，适合有固定发布节奏的团队。小团队与持续部署更适合主干开发。

## rebase 与 merge

`merge` 保留分支历史，产生合并提交；`rebase` 把当前分支的提交重放到目标分支之上，历史线性。原则：只对本地未推送的提交 rebase，已推送的公共分支不要 rebase，否则会改写他人历史。

交互式 rebase `git rebase -i HEAD~3` 可以合并、重排、修改提交，提交前整理历史很有用。

## cherry-pick

把某个提交应用到当前分支，适合把修复同步到多个分支。冲突时需要手动解决。cherry-pick 会生成新提交，原提交仍在原分支。

## 冲突解决

冲突标记包含当前分支（ours）与目标分支（theirs）。解决后 `git add` 标记已解决，再继续 rebase 或 merge。解决时不要盲目选一边，要理解两边意图。

## 暂存与撤销

- `git stash` 暂存工作区，切换分支时常用
- `git restore <file>` 丢弃工作区改动
- `git restore --staged <file>` 取消暂存
- `git reset --soft HEAD~1` 撤销提交但保留改动
- `git reset --hard` 丢弃改动，危险

`git revert` 生成反向提交，适合已推送的公共分支，安全可追溯。

## 提交规范

提交信息应说明“为什么改”，而不只是“改了什么”。常见格式：`type(scope): subject`，type 取 feat、fix、refactor、test、docs、chore。一个提交只做一件事，便于回滚与审查。

## PR 与代码审查

PR 应小而聚焦，描述包含背景、改动、验证方式。审查关注正确性、边界、可测性、安全，不纠结风格（交给格式化工具）。合并前确保 CI 通过。

## 标签与发布

`git tag -a v1.0.0 -m "..."` 创建附注标签，推送 `git push origin v1.0.0`。发布流程通常由标签触发 CI 构建产物并创建 Release。

## 常见坑

- 在公共分支上 rebase 后强推
- 提交了大文件或密钥
- 一个 PR 混入无关改动
- 用 reset 撤销已推送提交
- 提交信息只写“update”
- 忘记同步远端就开始开发
