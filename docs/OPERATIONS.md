# 运行和维护

[← 返回 README](../README.md)

## 行情数据和每日更新

行情数据所有用户共用一份。后端运行时，每个交易日收盘后自动更新全市场：行情（含估值与换手率）、新上市股票的全部历史、分红送转记录、指数行情、指数成分股、行业分类和历史股票池。当天行情还没发布或更新没完成时，30 分钟后再试，最晚到 23:30。白天手动运行时，如果当天的行情还没发布、但本地落后于最近一个交易日，会先把前几天补齐；管理后台和数据页会写明这次实际做了什么（例如“当天的行情还没有发布，先补到 10-19”），不只显示“完成”。被数据源拒绝（BaoStock 黑名单）时任务立刻停下，当天不再自动重试。下载数据、补历史数据、查看后台任务和配置 XTick 只有管理员可以操作；普通用户在数据更新页看到更新状态。数据文件先完整写好再整份替换，写到一半被中断（关闭程序、停电）也不会损坏原来的文件；后台数据任务不随启动窗口关闭，会继续运行到完成。

## 耗时计算的限制

所有用户共用一台服务器，耗时的计算有三条限制：每人同一时间只算一件，全站同时算的数量有上限（满了提示稍后再试），一件计算超过时间限制就停下。同样的因子评估或组合研究在同一份数据上算过就直接返回，数据每天更新以后重新计算。

## 账户和安全

未配置 SMTP 时密码重置不可用，开放注册也暂时不能注册（注册要先验证邮箱）；找回密码只填注册邮箱，验证码只发送至注册邮箱，不返回到浏览器。重置密码、修改密码和退出登录后，这个账户的旧登录令牌全部失效。用户可以在个人中心修改昵称（可以重名，每天最多 5 次，不能含违禁词）、修改密码和注销账户，注销会删除账户和全部研究数据；在设置页可以保存回测和 AI 研究员的默认值、查看今天剩余的免费 AI 次数（积分页面有余额、每一批的到期时间、价格、明细和兑换码），并把自己的全部数据导出成一个 JSON 文件（不含密码）。登录、注册和找回密码都有频率限制：同一 IP 15 分钟最多登录 30 次，同一邮箱连续输错 5 次密码要等 15 分钟，同一 IP 每小时最多注册 5 个账户。本机账户、行情、运行记录和密钥保存在后端 `data/` 中，不进入 Git。

## 用一个进程提供整个网站

正式部署时由后端直接提供打包好的网页，整个网站只有一个地址，不需要配置跨域。云服务器上用 `scripts/deploy.sh` 部署时会自动做下面这些事；手动在一台机器上运行时：

```bash
cd dashboard/backend
python -m pip install -r requirements.txt -c requirements.lock
cd ../..
scripts/serve.sh            # Windows：powershell -File scripts\serve.ps1
```

脚本先打包 `landing/` 和 `admin/`，再在 `127.0.0.1:8000` 启动后端，只开一个进程（次数限制和后台任务记在这个进程里，不要开多个 worker）。前面用 Cloudflare Tunnel 或 Nginx 提供 https，不直接暴露端口。上线前在 `.env` 里至少确认：`APP_SECRET`、管理员账户、`OPENROUTER_API_KEY`、`FELLOWQUANT_AI_DAILY_TOTAL`、注册方式（试用阶段建议用邀请码）、`FELLOWQUANT_CLIENT_IP_HEADER`、SMTP 和备份目录。`requirements.lock` 是测试通过的固定版本。

## 在自己的 Windows 电脑上公开（备用）

正式网站现在跑在云服务器上（见 [部署到云服务器](DEPLOY_SERVER.md)），下面的方法只在服务器出问题、需要临时用自己电脑顶上时使用。

先安装 cloudflared（`winget install --id Cloudflare.cloudflared`）。有托管在 Cloudflare 的域名时用正式 Tunnel，网址固定；先在这台电脑上做一次设置（`login` 会打开浏览器，选中域名授权）：

```powershell
cloudflared tunnel login
cloudflared tunnel create prismind
cloudflared tunnel route dns prismind getprismind.com
cloudflared tunnel route dns prismind www.getprismind.com
```

然后运行（下面每条命令都要带上同样的 `-Tunnel prismind -Hostname getprismind.com`；不带这两个参数就用临时 Tunnel）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\tunnel.ps1 -Tunnel prismind -Hostname getprismind.com            # 打包网页、在 127.0.0.1:8100 启动后端、连上 Cloudflare
powershell -ExecutionPolicy Bypass -File scripts\tunnel.ps1 -Tunnel prismind -Hostname getprismind.com -Install   # 以后登录 Windows 自动在后台启动（-Uninstall 取消）
powershell -ExecutionPolicy Bypass -File scripts\tunnel.ps1 -Status    # 是否在运行、当前网址
powershell -ExecutionPolicy Bypass -File scripts\tunnel.ps1 -Stop      # 停止
```

临时 Tunnel 的网址形如 `https://xxx.trycloudflare.com`，不需要 Cloudflare 账号，但**每次重新启动都会变**，只适合试用。当前网址在 `dashboard/backend/data/runtime/public-url.txt`。从编辑器或自动化工具的终端里启动时，脚本会自动转到后台运行（不在那个终端的进程组里），关掉终端网站也不会停。腾讯电脑管家、360 等安全软件可能会删掉“启动”文件夹里的快捷方式，`-Status` 显示“自动启动：未设置”时，要在安全软件里放行。脚本自动设置 `FELLOWQUANT_CLIENT_IP_HEADER=CF-Connecting-IP`，后端或 Tunnel 意外退出时自动重启，日志在 `dashboard/backend/data/runtime/logs/public-*.log`。用 8100 端口，和本机开发（`start.bat`，8000）可以同时运行。电脑睡眠、关机或退出登录时网站就访问不到了，要在电源设置里关掉自动睡眠。更新代码后先 `-Stop` 再启动，网页会重新打包。

## 服务条款和隐私政策

服务条款、隐私政策和风险提示在 `landing/src/legal/legalContent.js`（运营者、联系邮箱和生效日期在文件开头）；换服务器、换 AI 服务商或开始收费时要同步修改并更新生效日期，正式收费前请律师看一遍。
