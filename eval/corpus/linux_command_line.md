# Linux 命令行常用操作

## 文件与目录

`ls -la` 列出全部文件含隐藏文件与权限详情。`cd` 切换目录，`pwd` 显示当前位置。`cp -r` 递归复制，`mv` 移动或重命名，`rm -rf` 递归强制删除（极度危险，执行前确认路径）。

`find` 按条件查找：`find . -name "*.py" -mtime -1` 查找一天内修改的 Python 文件。`grep -rn` 递归搜索文本并显示行号。

## 权限

`chmod 755 file` 设置属主读写执行、组与其他读执行。`chown user:group file` 修改属主。目录需要执行权限才能进入。用 `umask` 控制新建文件默认权限。

## 进程管理

`ps aux` 查看进程，`top` / `htop` 实时监控。`kill -15 pid` 发送终止信号让进程优雅退出，`kill -9` 强制杀死（可能丢数据）。`nohup cmd &` 让进程脱离终端运行。

## 磁盘与内存

`df -h` 查看磁盘使用，`du -sh *` 查看目录大小。`free -h` 查看内存。磁盘满会导致日志写入失败、数据库异常，是最常见的线上故障之一。

## 网络

`curl -I` 只看响应头，`curl -X POST -d @file.json` 发送请求体。`ss -lntp` 查看监听端口。`ping` 测连通性，`traceroute` 看路径。`netstat` 在部分系统已废弃，`ss` 是替代品。

## 文本处理

`head` / `tail` 查看头尾，`tail -f` 跟随日志。`wc -l` 统计行数。`sort | uniq -c` 统计频次。`awk` 按列处理，`sed` 做替换。管道把命令串起来，`grep` 过滤后再交给下一步。

## 环境变量与启动

`export KEY=value` 设置当前会话变量，写入 `~/.bashrc` 或 `~/.zshrc` 才能持久。`source file` 在当前 shell 执行脚本。子进程继承环境变量，但父进程不会获得子进程的修改。

## systemd 服务

`systemctl start/stop/status myapp` 管理服务，`journalctl -u myapp -f` 跟随日志。服务文件放在 `/etc/systemd/system/`，定义执行命令、用户、重启策略。

## 常见坑

- 在错误目录执行 `rm -rf`
- 用 kill -9 停止数据库
- 修改 .bashrc 后没有 source
- 日志文件占满磁盘
- 端口被占用却查不到进程
- 在生产环境直接编辑配置不备份
