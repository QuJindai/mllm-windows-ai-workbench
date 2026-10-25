# Dream 桌面启动入口

更新日期：2026-10-25。

`scripts/start_dream_desktop.cmd` 是本机桌面启动器的版本管理源文件，对应部署文件 `E:/Dream/启用可选修脸.cmd`。桌面保留原来的 `启用可选修脸.cmd.lnk`，目标指向该部署文件，工作目录为 `E:/Dream`。

启动器使用 `%ProgramFiles%/PowerShell/7/pwsh.exe`，调用现有 `E:/Dream/repo/scripts/start_dream_web_background.ps1 -Port 8766`：

- 服务未启动时，在后台启动并等待就绪，再打开浏览器。
- 服务已经运行时，复用服务并打开 `http://127.0.0.1:8766/`，不会启动第二个实例。
- 启动失败时保留错误提示；服务日志在 `E:/Dream/logs`。
- 不再调用 `test-runs/face-polish-20260920/activate.ps1`，不会因为 8766 已有正常服务就直接退出。
- 修脸是人物创作页面的可选项，启动器不会自动勾选或提交生成任务，也不会自动重建前端或更新代码。

在现有 E 盘安装中同步启动器：

```powershell
Copy-Item -LiteralPath 'E:/Dream/repo/scripts/start_dream_desktop.cmd' -Destination 'E:/Dream/启用可选修脸.cmd' -Force
```

验收：部署 CMD 已实际执行，返回 `DREAM_WEB_ALREADY_RUNNING`，执行前后是同一个服务进程、一个监听；主页及当前前端脚本可访问。仓库源文件与已验证的部署文件 SHA-256 一致。此次启动器更新不改变人物模型、档案、生成参数或服务实现。
