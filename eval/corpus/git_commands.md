# Git 常用命令

Git 是分布式版本控制工具。改动文件后，先 `git add` 把修改放入暂存区，
再用 `git commit -m "说明"` 提交到本地仓库：

```bash
git add main.py
git commit -m "add startup script"
```

提交还在本地，用 `git push` 推送到远程仓库；第一次推送新分支要加
`-u origin 分支名`。反过来，`git clone <url>` 把远程仓库完整下载到本地，
`git pull` 拉取远程最新提交并合并。

## 分支与合并

新功能应该开分支开发：`git branch feature-x` 创建，
`git checkout feature-x` 切换（新版 Git 可用 `git switch`）。
开发完成后切回 main，执行 `git merge feature-x` 合并。

合并时如果两边改了同一行，Git 会报冲突并在文件里标出
`<<<<<<<`、`=======`、`>>>>>>>` 三段，需要手工选择保留内容后
重新 add、commit 完成合并。查看当前状态用 `git status`，
查看提交历史用 `git log --oneline`。
