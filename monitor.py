#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DAI 2026 Research Track 截止时间监控脚本

功能：
  1. 抓取 https://www.adai.ai/dai/2026/research-track.html 的 Important Dates 表格
  2. 与上次快照(last_dates.json)对比，检测到任何日期变动 -> 立即发【变更告警】邮件
  3. 计算距最近截止日期的天数，若 <= 阈值(默认7天) -> 发【倒计时】邮件，附随机祝福语
  4. 其余情况只写日志，不打扰

全程使用 Python 标准库，零第三方依赖。
环境变量(本地测试时手动设置；GitHub Actions 走 Secrets)：
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, MAIL_TO
"""

import os
import re
import sys
import json
import random
import smtplib
import datetime as dt
import urllib.request
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid

# ============== 配置 ==============
URL = "https://www.adai.ai/dai/2026/research-track.html"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_dates.json")
REMAIN_DAYS_THRESHOLD = 7          # 距最近截止 <= 该值才发倒计时邮件
HTTP_TIMEOUT = 30
USER_AGENT = "Mozilla/5.0 (DAI2026-Monitor/1.0)"

# 祝福语池 —— 朋友/同学语气。可自由增减，每天随机抽一条。
WISHES = [
    "deadline 再紧，也要记得好好吃饭、好好睡觉呀，加油，你一定可以的 🌱",
    "投稿只是生活的一部分，别给自己太大压力，慢慢来比较快 💪",
    "你已经走了很远了，剩下的几步也要稳稳地走，我看好你 ✨",
    "无论结果如何，认真准备的过程本身就值得被肯定，辛苦啦 ☕",
    "记得偶尔起身活动活动、看看窗外，身体才是革命的本钱 🌿",
    "焦虑的时候深呼吸三下，你已经具备解决它的能力了 🌈",
    "投稿不是孤军奋战，需要吐槽/帮忙随时叫我，一起冲 🔥",
    "今晚早点睡，明天脑子清醒了效率翻倍，别熬夜呀 🌙",
    "把大任务拆成小步走，每完成一步都给自己一点小奖励 🎁",
    "祝你文思泉涌、图表精美、实验一次性跑通、审稿人通情达理 🍀",
    "辛苦了这么久，再坚持一下下，曙光就在前方了 🌅",
    "做你自己就好，不必和别人比节奏，你的路有你的风景 🌸",
]

# ============== 日志 ==============
def log(msg):
    print(f"[{dt.datetime.now().isoformat(timespec='seconds')}] {msg}", flush=True)

# ============== 抓取 ==============
def fetch_html(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")

# ============== 解析 ==============
# 提取 Important Dates 表格区。锚点：<h2>Important Dates</h2> 到 </table>
_TABLE_RE = re.compile(
    r"<h2[^>]*>\s*Important Dates\s*</h2>(.*?)</table>",
    re.IGNORECASE | re.DOTALL,
)
# 每一行：<tr ...> <td>milestone</td> <td>date-html</td> <td>notes</td> </tr>
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
# 从日期单元格 HTML 里抽 <time datetime="YYYY-MM-DD">
_TIME_RE = re.compile(r'datetime="(\d{4}-\d{2}-\d{2})"', re.IGNORECASE)

def parse_dates(html):
    """
    返回 list[dict]，每项：
      milestone: 节点名
      date_raw : 日期单元格的原始内部 HTML（含 <s>/<time> 等标签，用于变更对比）
      notes    : 备注(纯文本)
      start    : 开始日期(YYYY-MM-DD)，从最新 <time datetime> 取（跳过 <s> 里的旧日期）
    """
    m = _TABLE_RE.search(html)
    if not m:
        raise RuntimeError("未找到 Important Dates 表格，页面结构可能已变更")
    table_html = m.group(1)

    results = []
    for row in _ROW_RE.finditer(table_html):
        cells = _CELL_RE.findall(row.group(1))
        if len(cells) < 2:
            continue
        milestone = _strip_tags(cells[0]).strip()
        if not milestone or milestone.lower() == "milestone":
            continue  # 跳过表头
        date_cell = cells[1]
        notes = _strip_tags(cells[2]).strip() if len(cells) >= 3 else ""

        # 变更对比用原始 HTML（去掉多余空白，但保留 <s>/<time> 结构信号）
        date_raw = re.sub(r"\s+", " ", date_cell).strip()

        # 倒计时用：取 <time datetime> 里的日期。
        # 关键：<s>旧日期</s> 通常不写在 <time> 标签里(本页面就是这样)，
        #       新日期才在 <time> 里 —— 所以只匹配 <time> 就天然跳过了被划掉的旧日期。
        times = _TIME_RE.findall(date_cell)
        start = times[0] if times else None

        results.append({
            "milestone": milestone,
            "date_raw": date_raw,
            "notes": notes,
            "start": start,
        })
    return results

def _strip_tags(s):
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()

# ============== 变更检测 ==============
def diff_dates(old_list, new_list):
    """
    对比两个解析结果，返回变更项 list[dict]:
      {milestone, old: date_raw, new: date_raw}
    按 milestone 名称做匹配；新增/删除行也算变更。
    """
    old_map = {r["milestone"]: r["date_raw"] for r in old_list}
    new_map = {r["milestone"]: r["date_raw"] for r in new_list}
    changes = []
    for ms, new_raw in new_map.items():
        if ms not in old_map:
            changes.append({"milestone": ms, "old": None, "new": new_raw})
        elif old_map[ms] != new_raw:
            changes.append({"milestone": ms, "old": old_map[ms], "new": new_raw})
    for ms, old_raw in old_map.items():
        if ms not in new_map:
            changes.append({"milestone": ms, "old": old_raw, "new": None})
    return changes

# ============== 倒计时 ==============
def nearest_upcoming(records, today=None):
    """
    返回 (record, days_left)；没有未来日期则返回 (None, None)。

    关键：用 d > today（严格大于今天）而非 d >= today。
    原因：截止当天一般已经在赶末班车，无需再提醒；更重要的是，
    若用 >= 会把当天(距0天)的 deadline 留作"最近"，挤掉本该接力
    上来的下一个 deadline，造成断档。
    例如 Abstract=7/27, Submission=8/3(差7天)：
      - 7/27 用 >= ：Abstract(0天) 仍是最近 → Submission 推迟到 7/30 才提醒(断档3天)
      - 7/27 用 >  ：Abstract 被排除     → Submission(7天) 立即接力 ✅
    """
    if today is None:
        today = dt.date.today()
    candidates = []
    for r in records:
        if not r["start"]:
            continue
        try:
            d = dt.date.fromisoformat(r["start"])
        except ValueError:
            continue
        if d > today:
            candidates.append((d, r))
    if not candidates:
        return None, None
    candidates.sort(key=lambda x: x[0])
    nearest_d, nearest_r = candidates[0]
    return nearest_r, (nearest_d - today).days

# ============== 邮件 ==============
def send_mail(subject, body_html):
    host = os.environ.get("SMTP_HOST")
    port = os.environ.get("SMTP_PORT", "465")
    user = os.environ.get("SMTP_USER")
    pwd = os.environ.get("SMTP_PASS")
    to = os.environ.get("MAIL_TO")
    if not all([host, user, pwd, to]):
        log("⚠️  SMTP 环境变量不全，跳过发信(仅写日志)：")
        log(f"    主题: {subject}")
        log("    正文(前200字): " + re.sub(r"<[^>]+>", "", body_html)[:200])
        return False
    msg = MIMEText(body_html, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr(("DAI 2026 监控", user))
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    try:
        port_i = int(port)
        if port_i == 465:
            smtp = smtplib.SMTP_SSL(host, port_i, timeout=HTTP_TIMEOUT)
        else:
            smtp = smtplib.SMTP(host, port_i, timeout=HTTP_TIMEOUT)
            smtp.starttls()
        smtp.login(user, pwd)
        smtp.sendmail(user, [x.strip() for x in to.split(",") if x.strip()], msg.as_string())
        smtp.quit()
        log(f"✉️  邮件已发送: {subject} -> {to}")
        return True
    except Exception as e:
        log(f"❌ 发信失败: {e}")
        return False

# ============== 邮件正文构造 ==============
def html_changes(changes, new_list):
    rows = ""
    for c in changes:
        old = _strip_tags(c["old"]) if c["old"] else "(无)"
        new = _strip_tags(c["new"]) if c["new"] else "(已删除)"
        rows += (
            f"<tr>"
            f"<td style='padding:6px;border:1px solid #eee;font-weight:600;'>{c['milestone']}</td>"
            f"<td style='padding:6px;border:1px solid #eee;color:#999;text-decoration:line-through;'>{old}</td>"
            f"<td style='padding:6px;border:1px solid #eee;color:#d33;font-weight:600;'>{new}</td>"
            f"</tr>"
        )
    full = "".join(
        f"<li><b>{r['milestone']}</b>: {_strip_tags(r['date_raw'])}</li>"
        for r in new_list
    )
    return f"""
    <div style="font-family:-apple-system,'Segoe UI',sans-serif;color:#333;max-width:640px;">
      <h2 style="color:#d33;">⚠️ DAI 2026 截止日期已变更</h2>
      <p>监控检测到 <a href="{URL}">Research Track 重要日期</a> 页面发生变动，请尽快确认：</p>
      <table style="border-collapse:collapse;font-size:14px;margin:12px 0;">
        <tr style="background:#fafafa;">
          <th style="padding:6px;border:1px solid #eee;">节点</th>
          <th style="padding:6px;border:1px solid #eee;">旧值</th>
          <th style="padding:6px;border:1px solid #eee;">新值</th>
        </tr>
        {rows}
      </table>
      <p style="color:#888;font-size:12px;">以下为当前完整日期表：</p>
      <ul style="font-size:14px;">{full}</ul>
      <p style="margin-top:16px;color:#888;font-size:12px;">—— DAI 2026 监控小助手</p>
    </div>
    """

def html_countdown(record, days, wish):
    name = record["milestone"]
    date_str = _strip_tags(record["date_raw"])
    urgency = "🔴" if days <= 2 else ("🟡" if days <= REMAIN_DAYS_THRESHOLD else "🟢")
    return f"""
    <div style="font-family:-apple-system,'Segoe UI',sans-serif;color:#333;max-width:560px;">
      <h2>{urgency} DAI 2026 ｜ 离 <span style="color:#1a73e8;">{name}</span> 还有 <span style="color:#d33;">{days}</span> 天</h2>
      <p>日期：<b>{date_str}</b></p>
      {f'<p style="color:#666;">备注：{record["notes"]}</p>' if record['notes'] and record['notes'] != '-' else ''}
      <p style="margin-top:16px;padding:12px 16px;background:#f5f7fa;border-left:3px solid #1a73e8;border-radius:4px;font-size:15px;">
        {wish}
      </p>
      <p style="margin-top:16px;font-size:13px;">
        📄 <a href="{URL}">查看完整 Call for Papers</a>
      </p>
      <p style="margin-top:12px;color:#888;font-size:12px;">—— 每日自动提醒，祝顺利</p>
    </div>
    """

# ============== 主流程 ==============
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f).get("dates", [])
        except Exception as e:
            log(f"读取状态文件失败，按初始化处理: {e}")
    return None  # 首次运行

def save_state(dates):
    payload = {
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "url": URL,
        "dates": dates,
    }
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

def main():
    log(f"开始监控: {URL}")
    try:
        html = fetch_html(URL)
    except Exception as e:
        log(f"❌ 抓取失败: {e}")
        return 2
    try:
        new_list = parse_dates(html)
    except Exception as e:
        log(f"❌ 解析失败: {e}")
        return 3
    log(f"解析到 {len(new_list)} 个日期节点:")
    for r in new_list:
        log(f"  - {r['milestone']} | raw={r['date_raw']!r} | start={r['start']}")

    old_list = load_state()
    is_first_run = old_list is None
    changes = [] if is_first_run else diff_dates(old_list, new_list)

    sent_any = False

    # 1) 变更告警(首次运行不发，避免初始化噪音)
    if changes:
        log(f"🔔 检测到 {len(changes)} 项变更:")
        for c in changes:
            log(f"    {c['milestone']}: {c['old']!r} -> {c['new']!r}")
        body = html_changes(changes, new_list)
        sent_any |= send_mail("⚠️ [DAI 2026] 截止日期已变更", body)
    elif is_first_run:
        log("🆕 首次运行，初始化快照，不发送告警")
    else:
        log("✅ 日期无变更")

    # 2) 倒计时
    rec, days = nearest_upcoming(new_list)
    if rec is not None:
        log(f"📅 最近截止: {rec['milestone']}，距今 {days} 天")
        if days <= REMAIN_DAYS_THRESHOLD:
            wish = random.choice(WISHES)
            body = html_countdown(rec, days, wish)
            sent_any |= send_mail(
                f"📅 DAI 2026 ｜ 离 {rec['milestone']} 还有 {days} 天",
                body,
            )
        else:
            log(f"💤 距截止还有 {days} 天(>{REMAIN_DAYS_THRESHOLD})，今日不发倒计时邮件")
    else:
        log("ℹ️  没有未来截止日期(可能会议已结束)")

    # 3) 保存快照(无论是否发信都存，作为下次对比基准)
    save_state(new_list)
    log(f"💾 快照已写入 {STATE_FILE}")
    log("完成" if sent_any else "完成(本次未发信)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
