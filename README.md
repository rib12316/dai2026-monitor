# DAI 2026 Research Track 截止时间监控

每天自动监控 [DAI 2026 Research Track](https://www.adai.ai/dai/2026/research-track.html) 的 Important Dates 页面：

- 🔔 **截止日期有变动** → 立即发**变更告警邮件**（高亮旧值→新值）
- 📅 **距最近截止 ≤ 7 天** → 每天发**倒计时邮件**，附带一句随机祝福语
- 💤 其余日子 → 静默不打扰，仅写日志

跑在 **GitHub Actions** 上，免费、免维护、不停机。零第三方依赖（纯 Python 标准库）。

---

## 📂 项目结构

```
dai2026-monitor/
├── .github/workflows/monitor.yml   # GitHub Actions 定时任务
├── monitor.py                       # 主脚本
├── last_dates.json                  # 状态文件(首次运行后自动生成并自动提交)
├── requirements.txt                 # 占位(无第三方依赖)
└── README.md
```

---

## 🚀 快速开始（5 步）

### 1. 把本项目推到 GitHub
新建一个 **private** 仓库（推荐私有，避免泄露邮箱），把整个 `dai2026-monitor` 目录推上去：

```bash
cd dai2026-monitor
git init
git add .
git commit -m "init: DAI 2026 deadline monitor"
git branch -M main
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

### 2. 准备一个 SMTP 发件邮箱

任选其一（推荐 QQ 邮箱，国内速度快、稳定）：

| 服务商 | SMTP_HOST | SMTP_PORT | 备注 |
|---|---|---|---|
| **QQ 邮箱** | `smtp.qq.com` | `465` | 需开启 SMTP 服务并生成"授权码" |
| 163 邮箱 | `smtp.163.com` | `465` | 需开启 SMTP，使用客户端授权码 |
| Gmail | `smtp.gmail.com` | `465` | 需开启两步验证 + 生成"应用专用密码" |
| Outlook | `smtp-mail.outlook.com` | `587` | 用账号密码即可(STARTTLS) |

> ⚠️ 不要直接用邮箱登录密码，要用各服务商提供的**授权码 / 应用专用密码**。

### 3. 在 GitHub 仓库里配置 5 个 Secrets

进入仓库 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**，依次添加：

| Name | Value 示例 |
|---|---|
| `SMTP_HOST` | `smtp.qq.com` |
| `SMTP_PORT` | `465` |
| `SMTP_USER` | `yourname@qq.com`（发件邮箱） |
| `SMTP_PASS` | 你的 SMTP 授权码（不是登录密码！） |
| `MAIL_TO` | `friend1@xx.com,friend2@yy.com`（收件人，多个用英文逗号分隔） |

### 4. 启用 Actions 定时任务

进入仓库 → **Actions** 标签页：
- 如果是 fork 来的仓库，会看到提示 **"I understand my workflows, go ahead and enable them"**，点击启用。
- 在左侧找到 **"DAI 2026 Deadline Monitor"** workflow。

### 5. 手动触发一次验证

在 Actions 页面：
1. 点击 **"DAI 2026 Deadline Monitor"**
2. 点击右侧 **"Run workflow"** 按钮 → **Run workflow**
3. 等待绿色对勾出现，去收件箱确认收到邮件 ✅

之后每天北京时间 **09:00 左右**会自动运行一次。

> ℹ️ GitHub 的 cron 不保证准时，可能延迟 5~30 分钟甚至更久（高峰期），这是平台限制，不影响功能。

---

## 🧪 本地测试

```bash
cd dai2026-monitor

# 方式 A: 不配 SMTP，只验证抓取+解析+倒计时(不发信只打日志)
python monitor.py

# 方式 B: 配置真实 SMTP 凭据，验证完整发信流程
# Windows (cmd)
set SMTP_HOST=smtp.qq.com
set SMTP_PORT=465
set SMTP_USER=yourname@qq.com
set SMTP_PASS=你的授权码
set MAIL_TO=you@xx.com
python monitor.py

# macOS / Linux
export SMTP_HOST=smtp.qq.com
export SMTP_PORT=465
export SMTP_USER=yourname@qq.com
export SMTP_PASS=你的授权码
export MAIL_TO=you@xx.com
python monitor.py
```

首次运行会生成 `last_dates.json` 快照，**不会**发变更告警（避免初始化噪音）。
想测试变更告警：手动编辑 `last_dates.json` 里某个 `date_raw` 字段，再跑一次即可看到告警邮件。

---

## ⚙️ 自定义配置

打开 `monitor.py`，顶部即可调整：

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `URL` | adai.ai 那个页面 | 监控目标 URL |
| `REMAIN_DAYS_THRESHOLD` | `7` | 距最近截止 ≤ 该值才发倒计时邮件，调大更频繁、调小更安静 |
| `WISHES` | 12 条 | 祝福语池，自由增删改，每天随机抽一条 |
| `USER_AGENT` | Mozilla/5.0 ... | 抓取时伪装的 UA，被反爬时换一个 |

**关于祝福语语气**：当前是朋友/同学语气，不带具体称呼（用"你"）。若想带称呼（如"小明"），把 `WISHES` 列表里的"你"替换成对应名字即可，或改成 `f"嘿 {name}，..."` 模板。

---

## 🔧 工作原理

1. `fetch_html()` 用 `urllib` 抓取页面 HTML
2. `parse_dates()` 用正则锚定 `Important Dates` 表格，提取每个 milestone 的：
   - `date_raw`：日期单元格**原始 HTML**（含 `<s>`/`<time>` 标签），用于变更对比 —— 这样官方任何细微改动都能捕获
   - `start`：从最新 `<time datetime="...">` 取的开始日期（天然跳过 `<s>` 里的旧日期）
3. `diff_dates()` 与 `last_dates.json` 快照对比，找出变更项
4. `nearest_upcoming()` 算出最近未来截止日期及剩余天数
5. 根据规则决定是否发邮件：变更必发；倒计时仅 ≤7 天发
6. 把本次解析结果写回 `last_dates.json`
7. workflow 最后一步：若 `last_dates.json` 有变化则自动 commit + push（带 `[skip ci]`）

---

## ❓ 常见问题

**Q: 为什么没收到邮件？**
- 检查 Actions 运行日志（绿色对勾点进去看 stdout），看是否走了"跳过发信"分支
- 检查收件人邮箱的**垃圾邮件**文件夹（首次很容易被过滤，标记为非垃圾即可）
- 检查 SMTP 授权码是否正确（不是登录密码）
- 检查 QQ/163 邮箱是否已开启 SMTP 服务

**Q: 为什么 Actions 没按 09:00 准时跑？**
- GitHub cron 不保证准时，延迟正常。如需更准，可在 workflow 里加一个 `delay` 的方案，或在 09:00/10:00 各设一个 cron 双保险。

**Q: 怎么停止监控？**
- Actions 页面 → 选中该 workflow → 右侧 "..." → **Disable workflow**。或直接删除仓库。

**Q: 想加更多通知渠道（微信/Telegram）？**
- 当前只支持邮件（按需求实现）。如需扩展，可参考 Server酱 / Telegram Bot API，在 `send_mail` 旁加个 `send_xxx` 函数即可。

---

## 📝 License

MIT — 随意使用。
