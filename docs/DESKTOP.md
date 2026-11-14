# 桌面图标 / Desktop shortcut

在当前已有 Python 的项目文件夹双击 create-desktop-shortcut.cmd，或 VS Code 终端运行 .\create-desktop-shortcut.cmd。此步骤由你在电脑上执行，因为桌面和个人程序目录不在当前助手的可写入范围。

首次运行会下载已发布的 Windows 运行包（约387MB），验证发布文件的 SHA256，完整安装到个人的 LocalAppData/Programs/PoloCopyTrade/v0.3.0-preview，并创建带 P 图标的桌面快捷方式。已有完整安装会复用，不重复下载。以后启动不需要项目文件夹或 Python。

双击桌面 Polo CopyTrade 会打开已运行的本机 Polo 页面；服务未运行时启动安装好的程序。打开不连接账户或自动交易。电脑和网络需保持运行才能持续跟随，网页可以关闭。

需要关闭隐藏服务时，先在页面停止账户跟随，再打开安装目录的 Close-Polo.cmd。它只停止此安装入口记录、且进程路径匹配的 Polo 程序，不会平掉交易所仓位。其他入口启动的服务需从对应入口关闭。

Run create-desktop-shortcut.cmd once from the existing source project. It downloads the published runtime, verifies its checksum, installs it in your user program directory, and creates a P desktop shortcut. Future starts do not depend on Python or the source folder. Existing Polo pages are reused; otherwise the installed app starts locally. No account is connected or trade started automatically. To close an owned hidden service, stop following first, then run Close-Polo.cmd from the install folder.
