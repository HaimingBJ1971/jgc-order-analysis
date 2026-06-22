#!/usr/bin/env python3
"""
从 263 企业邮箱读取最新一封「桌探日报」邮件，下载附件到本地。

主题示例：【桌探日报】2026-06-08 共 41 条
多封同类邮件时，按主题中的日期取最新一封（非邮件接收时间）。

263 企业邮箱在第三方客户端登录通常需「客户端授权码」，而非网页登录密码。
若 LOGIN 失败，请到网页邮箱 → 设置 → 账号安全 → 客户端授权码，生成后填入下方
EMAIL_PASSWORD 或通过 --password 传入。
"""
import argparse
import email
import imaplib
import os
import re
import ssl
import sys
from datetime import datetime, timedelta
from email.header import decode_header
from email.message import Message

import os

# ── 263 企业邮箱配置（密钥从环境变量读取）──────────────────────────
IMAP_HOST = os.environ.get("IMAP_HOST", "imap.263.net")
IMAP_PORT = int(os.environ.get("IMAP_PORT", "993"))
EMAIL_USER = os.environ.get("IMAP_USER", "")

SUBJECT_KEYWORD = "桌探日报"
SUBJECT_DATE_RE = re.compile(
    r"(\d{4})-(\d{1,2})-(\d{1,2})"
)


def decode_mime_header(value: str | None) -> str:
    if not value:
        return ""
    parts = []
    for chunk, charset in decode_header(value):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(chunk)
    return "".join(parts)


def parse_subject_date(subject: str) -> datetime | None:
    m = SUBJECT_DATE_RE.search(subject)
    if not m:
        return None
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def connect_imap(password: str) -> imaplib.IMAP4_SSL:
    if not EMAIL_USER:
        raise RuntimeError("未设置 IMAP_USER 环境变量（见 config/secrets.env）")
    if not password:
        raise RuntimeError("未设置 IMAP 密码/授权码（IMAP_PASSWORD 或 --password）")
    ctx = ssl.create_default_context()
    mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=ctx)
    try:
        mail.login(EMAIL_USER, password)
    except imaplib.IMAP4.error as exc:
        raise RuntimeError(
            "IMAP 登录失败。263 企业邮箱通常不允许直接用网页密码登录客户端，"
            "请到网页邮箱「设置 → 账号安全 → 客户端授权码」生成授权码，"
            f"再通过 --password 传入。原始错误: {exc}"
        ) from exc
    return mail


def _search_recent_uids(mail: imaplib.IMAP4_SSL) -> list[bytes]:
    """优先搜索近 120 天邮件，失败则回退全量。"""
    since = (datetime.now() - timedelta(days=120)).strftime("%d-%b-%Y")
    for criteria in (f'(SINCE "{since}")', "ALL"):
        status, data = mail.search(None, criteria)
        if status == "OK" and data and data[0]:
            return data[0].split()
    return []


def find_all_zhuotan_in_range(
    mail: imaplib.IMAP4_SSL,
    since: datetime,
    until: datetime,
    mailbox: str = "INBOX",
) -> list[tuple[int, str, datetime]]:
    status, _ = mail.select(mailbox, readonly=True)
    if status != "OK":
        raise RuntimeError(f"无法打开邮箱文件夹: {mailbox}")

    uids = _search_recent_uids(mail)
    results: list[tuple[int, str, datetime]] = []
    since_d = since.date()
    until_d = until.date()

    for uid_bytes in uids:
        uid = int(uid_bytes)
        status, msg_data = mail.fetch(uid_bytes, "(RFC822)")
        if status != "OK" or not msg_data or not msg_data[0]:
            continue
        raw = msg_data[0][1]
        if not isinstance(raw, (bytes, bytearray)):
            continue
        msg = email.message_from_bytes(raw)
        subject = decode_mime_header(msg.get("Subject"))
        if SUBJECT_KEYWORD not in subject:
            continue
        dt = parse_subject_date(subject)
        if dt is None:
            continue
        d = dt.date()
        if since_d <= d <= until_d:
            results.append((uid, subject, dt))

    if not results:
        raise RuntimeError(
            f"未找到 {since_d} ~ {until_d} 内主题含「{SUBJECT_KEYWORD}」的邮件"
        )
    results.sort(key=lambda x: x[2])
    return results


def find_latest_zhuotan_uid(mail: imaplib.IMAP4_SSL, mailbox: str = "INBOX") -> tuple[int, str, datetime]:
    status, _ = mail.select(mailbox, readonly=True)
    if status != "OK":
        raise RuntimeError(f"无法打开邮箱文件夹: {mailbox}")

    uids = _search_recent_uids(mail)
    if not uids:
        raise RuntimeError("收件箱为空或搜索失败")
    candidates: list[tuple[int, str, datetime]] = []

    for uid_bytes in uids:
        uid = int(uid_bytes)
        status, msg_data = mail.fetch(uid_bytes, "(RFC822)")
        if status != "OK" or not msg_data or not msg_data[0]:
            continue
        raw = msg_data[0][1]
        if not isinstance(raw, (bytes, bytearray)):
            continue
        msg = email.message_from_bytes(raw)
        subject = decode_mime_header(msg.get("Subject"))
        if SUBJECT_KEYWORD not in subject:
            continue
        dt = parse_subject_date(subject)
        if dt is None:
            continue
        candidates.append((uid, subject, dt))

    if not candidates:
        raise RuntimeError(f"未找到主题含「{SUBJECT_KEYWORD}」且带日期的邮件")

    candidates.sort(key=lambda x: x[2], reverse=True)
    return candidates[0]


def safe_filename(name: str) -> str:
    name = os.path.basename(name.strip() or "attachment")
    for ch in '\\/:*?"<>|':
        name = name.replace(ch, "_")
    return name or "attachment"


def iter_attachments(msg: Message):
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        filename = part.get_filename()
        if not filename:
            continue
        filename = decode_mime_header(filename)
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        yield filename, payload


def download_attachments(
    mail: imaplib.IMAP4_SSL,
    uid: int,
    output_dir: str,
) -> list[str]:
    status, msg_data = mail.fetch(str(uid).encode(), "(RFC822)")
    if status != "OK" or not msg_data or not msg_data[0]:
        raise RuntimeError(f"无法读取邮件 UID={uid}")

    raw = msg_data[0][1]
    if not isinstance(raw, (bytes, bytearray)):
        raise RuntimeError(f"邮件 UID={uid} 内容格式异常")

    msg = email.message_from_bytes(raw)
    os.makedirs(output_dir, exist_ok=True)

    saved: list[str] = []
    for filename, payload in iter_attachments(msg):
        path = os.path.join(output_dir, safe_filename(filename))
        with open(path, "wb") as f:
            f.write(payload)
        saved.append(path)

    if not saved:
        raise RuntimeError(f"邮件 UID={uid} 无附件")

    return saved


def fetch_zhuotan_range(
    output_dir: str,
    since: datetime,
    until: datetime,
    mailbox: str = "INBOX",
    password: str | None = None,
) -> list[dict]:
    pwd = password or os.environ.get("IMAP_PASSWORD", "")
    mail = connect_imap(pwd)
    saved_all: list[dict] = []
    try:
        candidates = find_all_zhuotan_in_range(mail, since, until, mailbox)
        for uid, subject, report_date in candidates:
            paths = download_attachments(mail, uid, output_dir)
            saved_all.append({
                "uid": uid,
                "subject": subject,
                "report_date": report_date.strftime("%Y-%m-%d"),
                "attachments": paths,
            })
        return saved_all
    finally:
        try:
            mail.logout()
        except Exception:
            pass


def fetch_latest_zhuotan(
    output_dir: str,
    mailbox: str = "INBOX",
    password: str | None = None,
) -> dict:
    pwd = password or os.environ.get("IMAP_PASSWORD", "")
    mail = connect_imap(pwd)
    try:
        uid, subject, report_date = find_latest_zhuotan_uid(mail, mailbox)
        paths = download_attachments(mail, uid, output_dir)
        return {
            "uid": uid,
            "subject": subject,
            "report_date": report_date.strftime("%Y-%m-%d"),
            "attachments": paths,
        }
    finally:
        try:
            mail.logout()
        except Exception:
            pass


def main():
    default_out = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "订单桌访合并")
    )
    parser = argparse.ArgumentParser(description="下载最新一封桌探日报邮件附件")
    parser.add_argument(
        "--output-dir",
        default=default_out,
        help=f"附件保存目录（默认: {default_out}）",
    )
    parser.add_argument(
        "--mailbox",
        default="INBOX",
        help="IMAP 文件夹名（默认: INBOX）",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="IMAP 客户端授权码（默认 IMAP_PASSWORD 环境变量）",
    )
    parser.add_argument(
        "--since",
        default=None,
        help="批量下载起始日期 YYYY-MM-DD",
    )
    parser.add_argument(
        "--until",
        default=None,
        help="批量下载结束日期 YYYY-MM-DD",
    )
    args = parser.parse_args()

    pwd = args.password or os.environ.get("IMAP_PASSWORD", "")
    print(f"连接 {IMAP_HOST}，账号 {EMAIL_USER or '(未设置 IMAP_USER)'} …")
    try:
        if args.since and args.until:
            since = datetime.strptime(args.since, "%Y-%m-%d")
            until = datetime.strptime(args.until, "%Y-%m-%d")
            results = fetch_zhuotan_range(args.output_dir, since, until, args.mailbox, pwd)
            for result in results:
                print(f"已选邮件: {result['subject']}")
                print(f"报告日期: {result['report_date']}  (UID={result['uid']})")
                for p in result["attachments"]:
                    print(f"  → {p}")
        else:
            result = fetch_latest_zhuotan(args.output_dir, args.mailbox, pwd)
            print(f"已选邮件: {result['subject']}")
            print(f"报告日期: {result['report_date']}  (UID={result['uid']})")
            print("已下载附件:")
            for p in result["attachments"]:
                print(f"  → {p}")
    except RuntimeError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
