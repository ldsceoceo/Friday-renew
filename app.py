#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Friday(fridaydev.fr) 自动续期（单账号 Cookie 版）
# Secrets：
#   COOKIE（必填，"remember_web_59ba36addc2b2f9401580f014c7f58ea4e30989d=<值>"，可附 "; user_id=<值>"）
#   EMAIL（可选，通知用备注名）
#   全局共用：GH_TOKEN / TG_BOT_TOKEN / TG_CHAT_ID / NODE_LINK(代理，可选)

import os, re, sys, time, json, requests, subprocess
from datetime import datetime
from seleniumbase import SB

GH_TOKEN      = os.environ.get("GH_TOKEN") or ""
TG_CHAT_ID    = os.environ.get("TG_CHAT_ID") or ""
TG_BOT_TOKEN  = os.environ.get("TG_BOT_TOKEN") or ""

BASE_URL      = "https://fridaydev.fr"
SERVICES_URL  = f"{BASE_URL}/services/"
DOMAIN        = "fridaydev.fr"

# 登录凭证：长命的是 remember_web_<hash>（后缀随站点变，只认前缀），后两个为改版前的旧格式
AUTH_COOKIE_NAMES = ("user_id", "PHPSESSID")
AUTH_COOKIE_PREFIXES = ("remember_web_",)


def is_auth_cookie(name) -> bool:
    name = name or ""
    return name in AUTH_COOKIE_NAMES or name.startswith(AUTH_COOKIE_PREFIXES)


def cookie_label(name: str) -> str:
    return (name[:18] + "…") if name.startswith(AUTH_COOKIE_PREFIXES) and len(name) > 18 else name


# Cookie 剩余有效期低于此天数则 TG 预警
EXPIRY_WARN_DAYS = 3
# 日志档位：默认只打关键里程碑；VERBOSE=true 时输出过程细节（定位/轮询/关闭动作）
VERBOSE = (os.environ.get("VERBOSE") or "false").lower() == "true"


def vlog(msg):
    if VERBOSE:
        print(msg)


def parse_cookie_str(raw: str):
    """把 "a=b; c=d" 解析成 [(name, value)]，值按第一个 = 切分，值内含 = 也安全。"""
    pairs = []
    for item in (raw or "").split(";"):
        item = item.strip()
        if not item or "=" not in item:
            continue
        name, value = item.split("=", 1)
        name, value = name.strip(), value.strip()
        if name and value:
            pairs.append((name, value))
    return pairs


def get_account():
    """单账号：读 COOKIE + EMAIL，缺 COOKIE 返回 None。"""
    raw = (os.environ.get("COOKIE") or "").strip()
    if not raw:
        return None
    return {"cookie_raw": raw,
            "email": (os.environ.get("EMAIL") or "").strip(),
            "secret_name": "COOKIE"}


def mask_email(email: str) -> str:
    if "@" in email:
        name, domain = email.split("@", 1)
        return f"{name[:2]}****{name[-2:]}@{domain}" if len(name) > 4 else f"{name}@{domain}"
    return (email[:2] + "****") if email else "（未填）"


def send_telegram_message(message: str):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("⚠️ Telegram 未配置，跳过通知")
        return
    try:
        requests.post(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
                      json={"chat_id": TG_CHAT_ID, "text": message}, timeout=10)
        print("✅ Telegram 文字通知已发送")
    except Exception as e:
        print(f"❌ Telegram 发送失败: {e}")


def send_telegram_photo(message: str, image_path: str):
    """TG 附截图通知（Xserver 方案），截图不存在或未配置则退化为纯文字。"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("⚠️ Telegram 未配置，跳过通知")
        return
    try:
        if image_path and os.path.isfile(image_path):
            with open(image_path, "rb") as f:
                r = requests.post(
                    f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto",
                    data={"chat_id": TG_CHAT_ID, "caption": message[:1000]},
                    files={"photo": (os.path.basename(image_path), f, "image/png")},
                    timeout=20)
            if r.status_code == 200:
                print("✅ Telegram 截图通知已发送")
                return
            print(f"⚠️ sendPhoto 失败({r.status_code})，降级为文字通知")
    except Exception as e:
        print(f"⚠️ 截图通知异常，降级为文字通知: {e}")
    send_telegram_message(message)


def update_github_secret(secret_name, new_value):
    if not new_value:
        print(f"⚠️ 跳过更新 {secret_name}：新值为空")
        return False
    print(f"🔄 更新 Secret: {secret_name}（长度 {len(new_value)}）")
    try:
        env = os.environ.copy()
        if GH_TOKEN:
            env["GH_TOKEN"] = GH_TOKEN
        proc = subprocess.run(["gh", "secret", "set", secret_name, "--body", new_value],
                              capture_output=True, text=True, timeout=30, check=False, env=env)
        if proc.returncode == 0:
            return True
        print(f"❌ 更新失败: {proc.stderr.strip()}")
        return False
    except Exception as e:
        print(f"❌ 异常: {e}")
        return False


def format_notification(status: str, email: str = "", extra: str = "",
                        error: str = "", old_due: str = "", new_due: str = "",
                        current_ip: str = "未知") -> str:
    """佬王同款（eooce 风，见技能族 tg-notify-style.md）：
    标题 + 状态 + 脱敏账号 + 前后到期双行 + 出口IP + 北京时间。"""
    now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() + 8 * 3600))
    lines = ["🎉 Friday 续期通知", "", f"{status}", f"👤 账号: {mask_email(email)}"]
    lines.append(f"📅 续期前到期：{old_due or '（未获取到）'}")
    lines.append(f"📅 续期后到期：{new_due or '（未获取到）'}")
    if extra:
        lines.append(extra)
    if error:
        lines.append(f"📝 {error}")
    lines.append(f"🌐 续期使用IP: {current_ip}")
    lines.append(f"🕒 续期时间：{now}")
    return "\n".join(lines)


def get_current_ip(proxy_server: str = "") -> str:
    proxies = {"http": proxy_server, "https": proxy_server} if proxy_server else None
    r = requests.get("https://api.ip.sb/ip", proxies=proxies, timeout=15)
    r.raise_for_status()
    return r.text.strip()


def extract_dates(page_text: str):
    """提取页面内 DD/MM/YYYY 日期（法语站格式），返回 datetime 列表。"""
    out = []
    for m in re.findall(r"\b(\d{2})/(\d{2})/(\d{4})\b", page_text or ""):
        try:
            out.append(datetime(int(m[2]), int(m[1]), int(m[0])))
        except ValueError:
            pass
    return out


def extract_renewal_date(sb):
    """优先从 .service-info 精确提取到期日（实测 HTML）：
    <div class="service-info"><span>Renouvellement</span><strong>13/10/2026</strong></div>
    找不到回落整页正则。单账号取首个命中；大小写不敏感（截图大写/源码首字母大写混用）。"""
    try:
        for el in sb.find_elements(".service-info"):
            try:
                t = el.text or ""
            except Exception:
                continue
            if "renouvellement" in t.lower():
                m = re.search(r"(\d{2})/(\d{2})/(\d{4})", t)
                if m:
                    try:
                        d = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                        vlog(f"🎯 精确到期日 (.service-info): {d.strftime('%d/%m/%Y')}")
                        return d
                    except ValueError:
                        pass
    except Exception:
        pass
    return None


def cookie_expiry_warning(sb) -> str:
    """检查长凭证 Cookie（remember_web_* / user_id / PHPSESSID）剩余有效期，
    取最宽松的那个作判据（站点会顺带种一堆短命 Cookie，只看长生命的那个），
    不足阈值返回预警文案，否则返回空串。"""
    try:
        candidates = [c for c in sb.get_cookies()
                      if is_auth_cookie(c.get("name")) and c.get("expiry")]
    except Exception as e:
        print(f"⚠️ Cookie 有效期检查异常: {e}")
        return ""
    if not candidates:
        vlog("ℹ️ 浏览器里没读到带过期时间的登录 Cookie，跳过有效期预警")
        return ""
    c = max(candidates, key=lambda x: x.get("expiry") or 0)
    name = cookie_label(c.get("name") or "")
    remain_days = (datetime.fromtimestamp(c["expiry"]) - datetime.now()).total_seconds() / 86400
    exp_str = datetime.fromtimestamp(c["expiry"]).strftime("%Y-%m-%d")
    if remain_days < EXPIRY_WARN_DAYS:
        return (f"🔔 Cookie 告警：{name} 仅剩 {remain_days:.1f} 天"
                f"（约 {exp_str} 过期），请尽快从浏览器重拷 COOKIE 更新 Secrets")
    print(f"🔑 {name} 剩余有效期约 {remain_days:.1f} 天（{exp_str} 过期）")
    return ""


def rebuild_cookie_str(sb, old_raw: str) -> str:
    """从浏览器最新 Cookie 重建 Secrets 串：优先取浏览器里的登录 Cookie（含改名的
    remember_web_*），缺失用旧值补；浏览器换了名的旧 remember_web_* 一并清掉。"""
    try:
        cookies = sb.get_cookies()
    except Exception:
        cookies = []
    browser = {c.get("name"): c.get("value") for c in cookies
               if c.get("value") and is_auth_cookie(c.get("name"))}
    old = dict(parse_cookie_str(old_raw))
    merged = dict(old)
    changed = False
    for name, value in browser.items():
        if value != old.get(name):
            merged[name] = value
            changed = True
    stale = [n for n in merged
             if n.startswith(AUTH_COOKIE_PREFIXES) and n not in browser]
    if stale and browser:
        for n in stale:
            del merged[n]
        changed = True
    if not changed:
        return ""
    return "; ".join(f"{k}={v}" for k, v in merged.items() if v)


def dismiss_cookie_banner(sb):
    """关闭 Cookie 同意横幅（Accepter），找不到就跳过。"""
    for sel in ['button:contains("Accepter")', 'button:contains("Accept")',
                'button:contains("Tout accepter")', '[id*="cookie"] button']:
        try:
            if sb.is_element_visible(sel):
                sb.click(sel)
                vlog("🍪 已关闭 Cookie 横幅")
                sb.sleep(1)
                return
        except Exception:
            pass


# ---------- 登录（HidenCloud 双通道结构，MVP 只实现 Cookie 通道） ----------

AUTH_CHECK_URL = "/php/auth.php"


def check_logged_in(sb):
    """同源问一次 /php/auth.php（站点自己的登录态来源，Cookie 由浏览器自动带上）。
    服务页对未登录访客也照样渲染 "Mes services"，光看文案会把失效 Cookie 判成成功。
    返回 True/False，接口异常或字段变更返回 None（交回文案判定）。"""
    try:
        raw = sb.execute_script(
            "var x = new XMLHttpRequest();"
            "x.open('GET', arguments[0], false);"
            "x.setRequestHeader('X-Requested-With', 'XMLHttpRequest');"
            "x.send();"
            "return x.status + '|' + (x.responseText || '');", AUTH_CHECK_URL)
    except Exception as e:
        vlog(f"ℹ️ {AUTH_CHECK_URL} 校验不可用，回落页面判定: {e}")
        return None
    status, _, body = str(raw or "").partition("|")
    compact = body.replace(" ", "")
    if '"isLoggedIn":true' in compact:
        return True
    if '"isLoggedIn":false' in compact or status == "401":
        return False
    vlog(f"ℹ️ {AUTH_CHECK_URL} 返回无法识别（HTTP {status}），回落页面判定")
    return None


def login_with_cookie(sb, cookie_raw) -> bool:
    pairs = parse_cookie_str(cookie_raw)
    if not pairs:
        print("❌ COOKIE 为空或格式错误（应为 a=b; c=d）")
        return False
    names = [n for n, _ in pairs]
    if not any(is_auth_cookie(n) for n in names):
        print(f"⚠️ COOKIE 里没有登录凭证（期望 remember_web_* / user_id / PHPSESSID），当前: {names}")
    sb.open(BASE_URL + "/")
    sb.wait_for_ready_state_complete()
    sb.sleep(2)
    try:
        sb.delete_all_cookies()
    except Exception:
        pass
    for name, value in pairs:
        err = None
        for dom in (DOMAIN, f".{DOMAIN}"):
            try:
                sb.add_cookie({"name": name, "value": value, "domain": dom})
                err = None
                break
            except Exception as e:
                err = e
        if err:
            print(f"⚠️ 注入 Cookie {name} 失败: {err}")
    sb.open(SERVICES_URL)
    sb.wait_for_ready_state_complete()
    sb.sleep(5)
    dismiss_cookie_banner(sb)
    try:
        text = sb.get_text("body")
    except Exception:
        text = ""
    url = sb.get_current_url()
    logged = check_logged_in(sb)
    # 通用判定：到达服务页且含 "Mes services"（不用硬编码用户名）
    page_ok = "Mes services" in text and "/services" in url
    if logged is True and page_ok:
        print("✅ Cookie 登录成功，已到达服务页")
        return True
    if logged is True:
        print(f"✅ Cookie 登录成功（auth.php 已确认），但未落在服务页，URL={url}")
        return True
    if logged is False:
        print(f"❌ Cookie 登录失败：{AUTH_CHECK_URL} 返回未登录（Cookie 失效或域名拷错，"
              f"需 fridaydev.fr 域下的，非 control.fridaydev.fr），URL={url}")
        return False
    if page_ok:
        print("✅ Cookie 登录成功，已到达服务页")
        return True
    print(f"❌ Cookie 登录失败，URL={url}")
    return False


def login_with_password(sb) -> bool:
    """账密备用通道（二期扩展位，MVP 未实现）。"""
    print("ℹ️ 账密备用通道尚未实现（MVP 仅 Cookie 登录）")
    return False


def login(sb, cookie_raw) -> bool:
    if login_with_cookie(sb, cookie_raw):
        return True
    print("🔄 Cookie 登录失败，尝试账密备用通道...")
    return login_with_password(sb)


# ---------- 续期（wabiss 三态判定移植） ----------

def find_renew_button(sb):
    """找可点的续期按钮；返回 (element, text)。Friday 同一按钮双态（2026-10 实测）：
    ① 未到时间："Renouvelable dans N jour(s)"倒计时态 —— 只通知不点（排除）；
    ② 可续期：到期后 Renouvelable 后面的文案会变化（如 "Renouveler gratuitement (5 jours)"，
       grounded 2026-09-28：<button class="btn-renew js-free-renew" data-uuid="...">）—— 这才是入口。
    判定：Renouvel* 且不带 "dans N jour" 倒计时才命中；倒计时走未到时间分支（见 find_not_yet_text）。"""
    # 快车道：功能类名定位（改版也不易动，比文案稳）；倒计时态按钮直接排除
    for sel in [".js-free-renew", ".btn-renew", "button[data-uuid]"]:
        try:
            if sb.is_element_visible(sel):
                el = sb.find_element(sel)
                t = (el.text or "").strip()
                if t and not re.search(r"dans\s*\d+\s*jour", t, re.IGNORECASE):
                    uuid = el.get_attribute("data-uuid") or ""
                    vlog(f"🎯 命中 grounded 选择器 ({sel}, data-uuid={uuid}): '{t}'")
                    return el, t
        except Exception:
            continue
    # 文案兜底：包含即命中（不再锚定结尾，兼容 "(5 jours)" 等后缀）；倒计时态排除
    seen = []
    try:
        btns = sb.find_elements("button, a")
    except Exception:
        return None, ""
    for el in btns:
        try:
            if not el.is_displayed():
                continue
            t = (el.text or "").strip()
            if not t:
                continue
            seen.append(t[:60])
            if (re.search(r"Renouvel", t, re.IGNORECASE)
                    and not re.search(r"dans\s*\d+\s*jour", t, re.IGNORECASE)):
                return el, t
        except Exception:
            continue
    if seen:
        print(f"🔍 未命中续期按钮，可见按钮文案: {seen[:15]}")
    return None, ""


def find_not_yet_text(page_text: str) -> str:
    m = re.search(r"Renouvelable dans\s*(\d+)\s*jours?", page_text or "", re.IGNORECASE)
    return f"{m.group(1)} 天" if m else ""


def solve_free_captcha(sb, tag) -> bool:
    """免费续期触发 428 captcha_required 时，fdCaptchaSolve 会弹 .fd-captcha-backdrop
   （官方注释：大多数情况 1-2 秒自动解）。backdrop 消失或拿到票据即算过。"""
    try:
        if not sb.is_element_visible(".fd-captcha-backdrop", timeout=8):
            return True  # 没弹验证，直接过
    except Exception:
        return True
    print(f"{tag} 🔒 弹出反机器人验证，先静等自动通过（官方多为 1-2 秒自解）...")
    for _ in range(15):  # 30 秒静等自解，别碰它
        sb.sleep(2)
        try:
            gone = not sb.is_element_visible(".fd-captcha-backdrop", timeout=1)
        except Exception:
            gone = True
        if gone:
            print(f"{tag} ✅ 验证自动通过")
            return True
    vlog(f"{tag} ⏳ 未自解，转手动点击...")
    for attempt in range(1, 4):
        try:
            sb.uc_gui_click_captcha()
        except Exception as e:
            vlog(f"{tag} ⚠️ 点击验证出错: {e}")
        for _ in range(6):
            sb.sleep(2)
            try:
                gone = not sb.is_element_visible(".fd-captcha-backdrop", timeout=1)
            except Exception:
                gone = True
            if gone:
                vlog(f"{tag} ✅ 验证层已消失")
                return True
            try:
                tok = sb.execute_script(
                    "try{return (typeof turnstile!=='undefined'&&turnstile.getResponse)?turnstile.getResponse():'';}catch(e){return '';}")
            except Exception:
                tok = ""
            if tok:
                vlog(f"{tag} ✅ 已拿到验证票据（长度 {len(tok)}）")
                return True
        vlog(f"{tag} ⏳ 第 {attempt} 次验证未通过，重试...")
    print(f"{tag} ❌ 验证最终未通过")
    return False


# ---------- CF Turnstile（eooce/Auto-Renew-HidenCloud 方法论移植到 SeleniumBase） ----------
# eooce 口径：表单/弹窗内嵌 Turnstile 多为非交互/自动模式，无需点击、约 8s 自出票据；
# 票据判定 = turnstile.getResponse()（索引 0~5）或隐藏 input 值长度 > 30；
# 有复选框才点（节流 6s+），点过且框消失即算过；20s 无框且没点过 → 视为无需验证直接过。
# 反检测沿用 SB UC 模式（undetected-chromedriver 内核）+ headful 真渲染，不碰 window.chrome。
CF_IFRAME_SEL = 'iframe[src*="challenges.cloudflare.com"]'


def _cf_turnstile_token(sb) -> str:
    """读 Turnstile 票据，有即代表验证通过（eooce _get_turnstile_token 同款逻辑）。"""
    try:
        return sb.execute_script(
            "try {"
            "  if (typeof turnstile !== 'undefined' && turnstile.getResponse) {"
            "    var t = null;"
            "    try { t = turnstile.getResponse(); } catch (e) {}"
            "    if (t && t.length > 30) return t;"
            "    for (var i = 0; i < 5; i++) {"
            "      try { t = turnstile.getResponse(String(i)); } catch (e) { t = null; }"
            "      if (t && t.length > 30) return t;"
            "    }"
            "  }"
            "} catch (e) {}"
            "var inputs = document.querySelectorAll("
            "  'input[name=\"cf-turnstile-response\"], input[id$=\"_response\"]');"
            "for (var k = 0; k < inputs.length; k++) {"
            "  if (inputs[k].value && inputs[k].value.length > 30) return inputs[k].value;"
            "}"
            "return '';") or ""
    except Exception:
        return ""


def _expand_cf_widget(sb):
    """把被盖住/压缩的验证框展开（orihost 同款），免得点不到。"""
    try:
        sb.execute_script(
            "document.querySelectorAll('.cf-turnstile').forEach(function(c){"
            "  c.style.overflow='visible';c.style.width='300px';c.style.height='65px';});"
            "document.querySelectorAll('iframe').forEach(function(f){"
            "  if(f.src&&f.src.indexOf('challenges.cloudflare.com')!==-1){"
            "    f.style.width='300px';f.style.height='65px';"
            "    f.style.visibility='visible';f.style.opacity='1';}});")
    except Exception:
        pass


def _click_cf_widget(sb) -> bool:
    """点验证框中心（自动模式下通常不需要，交互模式兜底）。"""
    _expand_cf_widget(sb)
    try:
        if sb.is_element_visible(CF_IFRAME_SEL, timeout=3):
            sb.click(CF_IFRAME_SEL, timeout=5)
            return True
    except Exception:
        pass
    try:
        sb.execute_script(
            "var f=document.querySelector('iframe[src*=\"challenges.cloudflare.com\"]');"
            "if(f){var r=f.getBoundingClientRect();"
            "var x=r.left+r.width/2,y=r.top+r.height/2;"
            "['mousedown','mouseup','click'].forEach(function(t){"
            "f.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,"
            "clientX:x,clientY:y,view:window}));});}")
        return True
    except Exception:
        return False


def solve_cf_turnstile(sb, tag="") -> bool:
    """点续期按钮后弹出的 CF 验证组件。节点纯净时自动模式几秒自过，直接返回 True；
    20s 无框且没点过 → 视为无需验证（eooce 启发式）；超时未出票据返回 False。"""
    try:
        has_frame = sb.is_element_visible(CF_IFRAME_SEL, timeout=20)
    except Exception:
        has_frame = False
    if not has_frame:
        vlog(f"{tag} ℹ️ 未检测到 CF 验证框，无需验证")
        return True
    print(f"{tag} 🔒 检测到 Cloudflare 验证，等待自动通过...")
    start = time.time()
    clicks = 0
    last_click = 0.0
    while time.time() - start < 90:
        if _cf_turnstile_token(sb):
            print(f"{tag} ✅ CF 验证通过（已拿到票据）")
            return True
        try:
            frame_gone = not sb.is_element_visible(CF_IFRAME_SEL, timeout=1)
        except Exception:
            frame_gone = True
        if frame_gone:
            # 框渲染后自行消失（自动通过/页面已推进）：视为通过，
            # 真正的仲裁交给后续日期对比，误判最多落到"结果未知"告警
            print(f"{tag} ✅ CF 验证框已消失，视为通过")
            return True
        if time.time() - last_click > 8:
            vlog(f"{tag} 🖱️ 点击 CF 验证框（第 {clicks + 1} 次）...")
            if _click_cf_widget(sb):
                clicks += 1
                last_click = time.time()
                sb.sleep(4)
                continue
        sb.sleep(2)
    if _cf_turnstile_token(sb):
        print(f"{tag} ✅ CF 验证通过（超时前命中票据）")
        return True
    print(f"{tag} ❌ CF 验证超时（90s 未出票据）")
    return False


def click_modal_confirm(sb, tag="") -> bool:
    """fdui 确认弹窗 grounded（录制 2026-09-28）：
    .fdui-overlay.fdui-open > .fdui-modal > .fdui-actions > button.fdui-btn-ghost
    （文案是自定义的"保留免费优惠"类，不是 Confirmer/Valider）。"""
    # 顺序（录制时间线）：点续期 → 428 → 验证 → 前端自动带票据 POST（200）→ 成功弹窗 → 点 ghost 确认。
    # 验证在前、弹窗在后，不可颠倒；且成功 POST 是前端自动发的，ghost 点击只是收尾。
    if not solve_free_captcha(sb, tag):
        try:
            sb.save_screenshot("captcha_fail.png")
        except Exception:
            pass
        return False
    try:
        sb.wait_for_element_visible(".fdui-overlay.fdui-open .fdui-modal", timeout=15)
    except Exception:
        print("⚠️ 未探测到 fdui 确认弹窗，走旧选择器兜底")
    # 枚举确认区按钮，启发式选"保留/确认"（排除 Annuler），兜底点最后一个（录制点的就是 ghost 位）
    try:
        raw = sb.find_elements(".fdui-overlay.fdui-open .fdui-actions button")
        cands = []
        for b in raw:
            try:
                if b.is_displayed():
                    cands.append((b, (b.text or "").strip()))
            except Exception:
                continue
        vlog(f"📝 确认区按钮: {[t for _, t in cands] or '（空）'}")
        order = []
        for b, t in cands:
            tl = t.lower()
            if "annuler" in tl or "cancel" in tl:
                continue
            if re.search(r"garder|conserver|gratuit|offre|confirmer|valider|renew|^ok$", tl):
                order.insert(0, (b, t))
            else:
                order.append((b, t))
        if not order and cands:
            order = [cands[-1]]
        for b, t in order:
            try:
                b.click()
                print(f"✅ 已点击确认按钮: '{t[:60]}'")
                return True
            except Exception:
                try:
                    sb.execute_script("arguments[0].click();", b)
                    print(f"✅ 已 JS 点击确认按钮: '{t[:60]}'")
                    return True
                except Exception:
                    continue
    except Exception as e:
        print(f"⚠️ 枚举确认按钮异常: {e}")
    for sel in [".modal.show button.btn-primary", ".modal.show button",
                ".swal2-confirm", 'button:contains("Confirmer")',
                'button:contains("Valider")', 'button:contains("Confirm")']:
        try:
            if sb.is_element_visible(sel):
                sb.click(sel, timeout=3)
                print(f"✅ 已点击确认弹窗 ({sel})")
                return True
        except Exception:
            pass
    print("⚠️ 未找到确认弹窗按钮（可能无需确认，直接检查结果）")
    return False


def close_success_notice(sb, tag=""):
    """过盾后弹出的成功通知（toast 右上 × / 成功弹窗 OK），直接关闭即可。
    注意：绝不碰 .fd-captcha-cancel（那是"取消订单"）。"""
    try:
        if sb.is_element_visible(".fdui-toast-close", timeout=3):
            txt = ""
            try:
                toast = sb.find_element(".fdui-toast")
                txt = (toast.text or "").strip().replace("\n", " ")[:120]
            except Exception:
                pass
            sb.click(".fdui-toast-close", timeout=3)
            print(f"{tag} 🔕 已关闭成功通知: '{txt}'")
            return True
    except Exception:
        pass
    try:
        body = sb.get_text(".fdui-overlay.fdui-open .fdui-modal") or ""
    except Exception:
        body = ""
    if body and re.search(r"renouvel|success|succès|5 jours", body, re.IGNORECASE):
        vlog(f"{tag} 🎉 成功弹窗: '{body.strip().replace(chr(10), ' ')[:120]}'")
        for sel in ['.fdui-overlay.fdui-open [data-act="ok"]',
                    '.fdui-overlay.fdui-open .fdui-actions button:last-child']:
            try:
                if sb.is_element_visible(sel, timeout=3):
                    sb.click(sel, timeout=3)
                    print(f"{tag} 🔕 已关闭成功弹窗 ({sel})")
                    return True
            except Exception:
                continue
    return False


def renew(sb, cookie_raw, email, current_ip="未知") -> dict:
    result = {"ok": False, "summary": "未知"}
    shot = "result.png"

    if not login(sb, cookie_raw):
        msg = format_notification("❌ 登录失败", email=email, current_ip=current_ip,
                                  error="Cookie 已失效，请从浏览器重拷 COOKIE 更新 Secrets")
        send_telegram_message(msg)
        result["summary"] = "❌ 登录失败（Cookie 失效）"
        return result

    try:
        page_text = sb.get_text("body")
    except Exception:
        page_text = ""
    old_dates = extract_dates(page_text)
    old_max = extract_renewal_date(sb) or (max(old_dates) if old_dates else None)
    print(f"📅 当前页面日期: "
          f"{[d.strftime('%d/%m/%Y') for d in old_dates] or '（未提取到）'}")

    # 未到时间态
    not_yet = find_not_yet_text(page_text)
    btn, btn_text = find_renew_button(sb)

    if btn is None and not_yet:
        print(f"⏳ 未到续期时间：{not_yet} 后可续")
        send_telegram_message(format_notification(
            "⏳ 未到续期时间", email=email, current_ip=current_ip,
            extra=f"⏱️ {not_yet}后可续",
            old_due=old_max.strftime("%d/%m/%Y") if old_max else "（未获取到）"))
        result.update(ok=True, summary=f"⏳ 未到时间（{not_yet}后）")

    elif btn is not None:
        tag = f"[{email}]" if email else ""
        print(f"✅ 发现续期按钮: '{btn_text}'，点击...")
        try:
            btn.click()
        except Exception:
            try:
                sb.execute_script("arguments[0].click();", btn)
            except Exception as e:
                err = f"点击续期按钮失败: {e}"
                print(f"❌ {err}")
                send_telegram_message(format_notification("❌ 续期失败", email=email, current_ip=current_ip, error=err))
                result["summary"] = "❌ 续期失败（点击按钮出错）"
                return result
        sb.sleep(4)
        # 点按钮后弹 CF 验证组件（Turnstile）：节点纯净自动过盾，过盾即默认续期完成；
        # 无框（旧 Renouveler 流程/已验证过）直接返回 True 继续走 fdCaptcha + 确认弹窗
        if not solve_cf_turnstile(sb, tag):
            try:
                sb.save_screenshot("cf_fail.png")
            except Exception:
                pass
            err = "CF 验证未通过（Turnstile 90s 未出票据），请检查节点纯净度后手动重试"
            print(f"❌ {err}")
            send_telegram_message(format_notification("❌ 续期失败", email=email, current_ip=current_ip, error=err))
            result["summary"] = "❌ 续期失败（CF 验证未通过）"
            return result
        click_modal_confirm(sb, tag)
        sb.sleep(3)
        close_success_notice(sb, tag)
        vlog("⏳ 等待结果并刷新...")
        sb.sleep(5)
        try:
            sb.execute_script("location.reload();")
        except Exception:
            sb.open(SERVICES_URL)
        sb.wait_for_ready_state_complete()
        sb.sleep(5)
        try:
            new_text = sb.get_text("body")
        except Exception:
            new_text = ""
        new_dates = extract_dates(new_text)
        new_max = extract_renewal_date(sb) or (max(new_dates) if new_dates else None)
        ok = False
        if old_max and new_max and new_max > old_max:
            ok = True
        elif "Actif" in new_text and "Suspendu" not in new_text and not find_not_yet_text(new_text):
            ok = True  # 日期未变但状态活跃（可能续期即时生效无日期变化）
        try:
            sb.save_screenshot(shot)
        except Exception:
            shot = ""
        if ok:
            print(f"✅ 续期成功，新日期: "
                  f"{[d.strftime('%d/%m/%Y') for d in new_dates] or '（状态活跃）'}")
            send_telegram_photo(format_notification(
                "✅ 续期成功", email=email, current_ip=current_ip,
                old_due=old_max.strftime("%d/%m/%Y") if old_max else "",
                new_due=new_max.strftime("%d/%m/%Y") if new_max else "（状态活跃）"), shot)
            result.update(ok=True,
                          summary=f"✅ 续期成功（到期 {new_max.strftime('%d/%m/%Y') if new_max else '活跃'}）")
        else:
            print("⚠️ 续期结果未知，请手动检查")
            send_telegram_photo(format_notification(
                "⚠️ 续期可能未成功", email=email, current_ip=current_ip, extra="请登录后台检查",
                old_due=old_max.strftime("%d/%m/%Y") if old_max else "（未获取到）"), shot)
            result["summary"] = "⚠️ 结果未知（请手动检查）"
    else:
        print("ℹ️ 未找到续期按钮/倒计时，状态未知")
        send_telegram_message(format_notification(
            "ℹ️ 状态未知", email=email, current_ip=current_ip, extra="未找到续期按钮，请手动检查",
            old_due=old_max.strftime("%d/%m/%Y") if old_max else "（未获取到）"))
        result["summary"] = "ℹ️ 状态未知"

    # Cookie 有效期预警 + 自动回写
    warn = cookie_expiry_warning(sb)
    if warn:
        print(warn)
        send_telegram_message(format_notification("🔔 Cookie 有效期预警", email=email, current_ip=current_ip, extra=warn))
    new_raw = rebuild_cookie_str(sb, cookie_raw)
    if new_raw:
        vlog("🔄 浏览器 Cookie 有更新，回写 Secrets...")
        if GH_TOKEN:
            print('✅ 回写成功' if update_github_secret("COOKIE", new_raw) else '⚠️ 回写失败，请检查 GH_TOKEN')
        else:
            print("⚠️ 未设置 GH_TOKEN，无法自动回写")
    else:
        vlog("✅ Cookie 无需更新")
    return result


def main():
    print("#" * 25)
    print("   Friday 自动续期（单账号）")
    print("#" * 25)

    acct = get_account()
    if not acct:
        print("ℹ️ 未配置 COOKIE，脚本终止。Secrets 里填 COOKIE（格式 a=b; c=d）。")
        sys.exit(1)

    IS_PROXY = os.environ.get("IS_PROXY", "false").lower() == "true"
    PROXY_SERVER = os.environ.get("PROXY_SERVER", "").strip() or "http://127.0.0.1:1080"
    HEADLESS = os.environ.get("HEADLESS", "false").lower() == "true"  # CF Turnstile 需 headful 真渲染（eooce 口径），CI 跑在 xvfb 虚拟屏上
    sb_kwargs = {"uc": True, "headless": HEADLESS}
    print(f"🔗 {'挂载代理: ' + PROXY_SERVER if IS_PROXY else '🍭 未使用代理，直连访问'}")
    if IS_PROXY:
        sb_kwargs["proxy"] = PROXY_SERVER

    with SB(**sb_kwargs) as sb:
        current_ip = "未知"
        try:
            current_ip = get_current_ip(PROXY_SERVER if IS_PROXY else '')
            print(f"📍 当前出口IP: {current_ip}")
        except Exception as e:
            print(f"⚠️ 获取出口 IP 失败: {e}")
        try:
            result = renew(sb, acct["cookie_raw"], acct["email"], current_ip)
        except Exception as e:
            print(f"❌ 执行异常: {e}")
            import traceback
            traceback.print_exc()
            result = {"ok": False, "summary": f"❌ 执行异常：{e}"}
            try:
                send_telegram_message(format_notification(
                    "❌ 续期失败", email=acct["email"], current_ip=current_ip, error=f"执行异常：{e}"))
            except Exception:
                pass

    print(f"\n🏁 执行完毕：{result['summary']}")


if __name__ == "__main__":
    main()
