# 配置说明

[← 返回 README](../README.md)

所有配置项都写在 `dashboard/backend/.env` 里（从同目录的 `.env.example` 复制一份再改）。配置项的名字以 `FELLOWQUANT_` 开头，这是项目改名为镜思 Prismind 以前的名字，为了不影响已经部署的网站保留了下来。

将 `dashboard/backend/.env.example` 复制为同目录的 `.env`，填写需要的配置；后端启动时自动读取。模型密钥由服务器统一配置。AI 模型和密钥、AI 次数、每日更新、BaoStock 请求间隔、邮件服务和 WeKnora 也可以由管理员在管理后台的“系统设置”里改，保存后立刻生效，优先于 `.env`；改回用 `.env` 时清除后台的设置即可。`.env` 不进入 Git。

| 配置 | 用途 |
| --- | --- |
| `APP_SECRET` | 登录令牌签名；留空时自动生成并持久化本机随机密钥 |
| `FELLOWQUANT_ADMIN_EMAIL` / `FELLOWQUANT_ADMIN_PASSWORD` | 首次创建管理员，初始密码至少 12 位；不提供公共默认密码 |
| `OPENROUTER_API_KEY` | 平台统一提供的 AI 模型（AI 个股分析、用一句话生成规则），也用于 Jev 决策服务；用户不需要自己填写密钥 |
| `TYPESAFE_API_KEY` / `JEV_API_KEY` | TypeSafe 官方 Jev 密钥（前者优先）；配置后 Jev 独立于聊天模型，默认调用官方 `/v1/systemone`，未配置时使用 OpenRouter |
| `FELLOWQUANT_AI_MODEL` / `FELLOWQUANT_AI_BASE_URL` | 可选：换模型或换成其他 OpenAI 兼容服务（默认 OpenRouter 上的 `deepseek/deepseek-v4-pro`）；换服务时用 `FELLOWQUANT_AI_API_KEY` 填它的密钥 |
| `FELLOWQUANT_AI_MODEL_BRIEF` / `_SCREEN` / `_QUESTION` / `_CHAT` / `_STRATEGY` | 可选：AI 解读、选股解读、追问、AI 问答、一句话生成规则各自用的模型（例如追问和 AI 问答用快的 flash，AI 解读和选股解读用强的 pro）；和默认的文本模型用同一个接口地址和密钥，留空就用 `FELLOWQUANT_AI_MODEL`。也可以在管理后台“系统设置 → AI 模型”里改 |
| `FELLOWQUANT_AI_DAILY_BRIEFS` / `_QUESTIONS` / `_STRATEGIES` / `_REVIEWS` / `_DECISIONS` / `_CHATS` | 可选：每人每天免费的 AI 分析、追问、生成规则、AI 评估（回测评估和决策辅助）、个股判断（AI 个股分析里的 Jev）、AI 问答次数（默认 3 / 10 / 5 / 3 / 3 / 10），用完以后每次扣积分；管理员不限、不扣积分。AI 问答每问一次算一次（内部调用两次模型） |
| `FELLOWQUANT_POINTS_SIGNUP` / `_GIFT_DAYS` / `_CHECKIN` / `_CHECKIN_STEP` / `_CHECKIN_MAX` / `_CHECKIN_DAYS` / `_MAKEUP_EVERY` / `_MAKEUP_WINDOW` / `_DAILY_CAP` / `_COST_BRIEF` …… | 可选：积分。新用户送多少（默认 100，每个邮箱一次：注销后用同一个邮箱重新注册不再送，同一个邮箱的不同写法如 `a+1@` 算同一个；以前注册的账户第一次打开时补上）、赠送的积分多少天有效（默认 30）、每日打卡（北京时间每天一次；连续第 1 天送 5，每多一天多送 2，最多 15，断了从头开始；打卡的积分 30 天有效；累计真正打卡 7 天送一张不过期的补签卡，可以补最近 7 天内漏打的一天，只接上连续天数、不送积分；第 1 天送 0 就关闭打卡）、每人每天最多用几次 AI（默认 200，免费的加积分的，0 不限）、免费次数用完以后每次多少积分（默认 AI 解读 3、追问 1、生成规则 2、AI 评估 2、个股判断 2、AI 问答 2）。模型没有回答时不扣积分；扣的时候先扣快到期的。积分来自注册赠送、每日打卡、兑换码和管理员发放，充值以后再开 |
| `FELLOWQUANT_JEV_MODEL` / `FELLOWQUANT_JEV_URL` | 可选：决策模型和完整接口地址；TypeSafe 默认 `jev-latest`，OpenRouter 默认 `typesafe/jev-1.13`。密钥必须与服务匹配 |
| `FELLOWQUANT_DAILY_UPDATE` / `FELLOWQUANT_DAILY_UPDATE_TIME` | 每个交易日收盘后自动更新全市场数据（默认开启，北京时间 18:05 以后：BaoStock 大约 17:30 发布当天日线、18:00 发布复权因子；还没发布时每 10 分钟再查一次）；填 `off` 关闭，管理员仍可在数据更新页手动运行 |
| `FELLOWQUANT_FUNDAMENTALS_UPDATE` | 财报季自动更新财务数据（默认开启）：1～4 月、7～8 月、10 月以及 5、9、11 月第一周的每个周六 10:00 以后，下载最近 5 个报告期里还没有的财报；填 `off` 关闭，管理员仍可以在管理后台手动更新 |
| `FELLOWQUANT_BAOSTOCK_INTERVAL` | 每两次 BaoStock 请求之间至少隔几秒（默认 0.1）。BaoStock 会把短时间内请求太多的服务器暂时拉黑（提示“黑名单用户”）；被拒绝时数据任务立刻停下、当天不再自动重试，页面上会写明原因。经常被拉黑时调大这个数 |
| `FELLOWQUANT_FACTOR_PROFILE` | AI 个股分析的因子画像：后端每 10 分钟检查一次，把最新交易日的全市场因子值预先算好（约半分钟，存在 `data/runtime/factor_profiles`）；填 `off` 关闭预先计算，分析时仍会在后台现算 |
| `FELLOWQUANT_COMPUTE_SLOTS` / `_PER_USER` / `_TIMEOUT` / `_CACHE` | 耗时计算（回测、参数验证、因子评估与组合研究）的限制：全站同时最多几件（默认 CPU 核数的一半，2 到 4）、每人同时几件（默认 1）、一件最多多少秒（默认 600）、记住多少份因子研究结果（默认 64） |
| `FELLOWQUANT_AI_DAILY_TOTAL` | 全站每天最多调用多少次 AI（默认 500，管理员不计），防止费用失控；用完以后当天所有用户暂停 AI 功能 |
| `WEKNORA_BASE_URL` / `WEKNORA_API_KEY` | WeKnora 服务地址与空间 Key，也可由管理员在页面配置；没有配置时知识库问答不可用 |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_FROM` | 发注册验证码和密码重置验证码的邮件服务；端口 465、994 用 SSL（163 邮箱：`smtp.163.com`、465，密码填授权码），别的端口用 STARTTLS（默认 587）。也可以在管理后台“系统设置 → 邮件服务”里填 |
| `FELLOWQUANT_SIGNUP_EMAIL_CODE` | 注册时验证邮箱（默认开）：配好邮件服务以后，注册要先填发到邮箱的验证码；没配邮件服务时开放注册暂时不能注册，凭邀请码注册照常。填 `off` 关闭，只用于自己电脑上试用 |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | SMTP 登录凭据（邮件服务需要时填写） |
| `FELLOWQUANT_REGISTRATION` / `FELLOWQUANT_INVITE_CODES` | 注册方式和邀请码一般在管理后台的“注册与邀请码”里设置，改完立即生效。这两项只是默认值：在页面上选过注册方式以后以页面为准；`.env` 里的邀请码（`码:次数`，逗号分开，例如 `TRIAL2026:20,FRIEND`，不写次数就不限次数）和页面生成的一起有效；`FELLOWQUANT_REGISTRATION=closed` 会固定暂停注册，页面上也改不了 |
| `FELLOWQUANT_CLIENT_IP_HEADER` | 部署在 Cloudflare 或 Nginx 后面时，从哪个请求头读取用户的真实 IP（Cloudflare 填 `CF-Connecting-IP`），用于登录、注册的频率限制 |
| `FELLOWQUANT_CORS_ORIGINS` | 允许跨域访问的网页地址，逗号分开；默认只允许本机开发服务器。前后端同一个地址时不需要 |
| `FELLOWQUANT_STATIC_DIR` / `FELLOWQUANT_ADMIN_DIR` | 打包好的网页目录（`landing/dist`）和管理后台目录（`admin/dist`，在 `/admin/` 下），设置后后端直接提供网页，见 [运行和维护](OPERATIONS.md#用一个进程提供整个网站) |
| `FELLOWQUANT_API_DOCS` | 填 `on` 打开接口文档 `/docs`（默认关闭；`scripts/start.ps1` 本机开发时自动打开） |
| `FELLOWQUANT_MAX_BODY_MB` | 一次请求最大多少 MB（默认 5），超过返回 413 |
| `FELLOWQUANT_BACKUP` / `_BACKUP_DIR` / `_BACKUP_KEEP` | 每天自动备份账户数据库、登录密钥和数据源、知识库设置（默认开启，放在 `data/backups`，保留 14 份）；备份目录最好设在另一块硬盘或同步盘；行情数据可以重新下载，不备份 |
| `FELLOWQUANT_PASSWORD_ITERATIONS` | 密码加密的计算轮数（默认 600000），一般不用改；旧账户登录时自动升级 |

## AI 服务：Jev 和 WeKnora

WeKnora 需要预先部署、创建知识库，并为 Key 开通相应的读取、检索和聊天权限。AI 个股分析的文字解读和“用一句话生成规则”使用平台的聊天模型；没有配置时，生成规则改用离线规则识别。决策模型 Jev 按概率回答选择、是非、评分三类问题：AI 个股分析可只使用 Jev 归纳当前数据里“利好较多 / 大致相当 / 风险较多”（只描述现有数据，不预测价格；页面只显示归纳和模型的把握，不显示三者的概率），无需文本模型；回测结果页用它评估风险等级和过度拟合的可能。材料由平台从本地数据自动整理，结果按账户保存，重复打开不再计费；独立判断计入每日评估额度。TypeSafe 的请求协议见[官方文档](https://docs.typesafe.ai/api)。

需要验证实际集成时，在项目根目录运行 `python scripts/verify_jev.py --live`。该命令会向配置的 Jev 服务发送本地行情和回测摘要，消耗 API 额度；使用独立账户数据库，报告保存在 Git 忽略的 `outputs/`，不会修改现有账户和行情。

完整的配置、网页操作、API 示例、额度说明和故障排查见 [Jev 使用文档](JEV_USAGE.md)。
