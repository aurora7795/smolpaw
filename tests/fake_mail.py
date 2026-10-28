"""
Fake SMTP and IMAP test server running on 127.0.0.1.
Used to test email tools without a real mailbox.

Run standalone:
  .venv/bin/python tests/fake_mail.py [smtp_port] [imap_port]
"""

import base64
import email
import email.message
import email.policy
import email.utils
import re
import shlex
import socketserver
import sys
import threading
import time
from dataclasses import dataclass, field

HOST = "127.0.0.1"
DEFAULT_SMTP_PORT = 8766
DEFAULT_IMAP_PORT = 8767
TEST_USER = "test"
TEST_PASSWORD = "test"


@dataclass
class SmtpMessage:
    """A message received via SMTP."""

    sender: str
    recipients: list[str]
    raw: str
    raw_headers: str
    body: str
    headers: dict[str, str] = field(default_factory=dict)
    subject: str = ""


@dataclass
class ImapMessage:
    """A message stored in an IMAP mailbox."""

    uid: int
    sender: str
    to: str
    subject: str
    body: str
    date: str
    headers: dict[str, str]
    raw: bytes
    flags: set[str] = field(default_factory=set)


def _imap_escape(text: str) -> str:
    """Escape backslashes and double quotes for IMAP quoted strings."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _format_addr(raw_addr: str) -> str:
    """Format an email address into an IMAP address structure."""
    if not raw_addr:
        return "NIL"
    name, addr = email.utils.parseaddr(raw_addr)
    mailbox, _, host = addr.partition("@")
    name_str = f'"{_imap_escape(name)}"' if name else "NIL"
    mbx_str = f'"{_imap_escape(mailbox)}"' if mailbox else '""'
    host_str = f'"{_imap_escape(host)}"' if host else '""'
    return f'(({name_str} NIL {mbx_str} {host_str}))'


def _format_envelope(msg: ImapMessage) -> str:
    """Format an IMAP ENVELOPE structure (RFC 3501 Section 7.4.2)."""
    date_str = f'"{_imap_escape(msg.date)}"' if msg.date else '""'
    subj_str = f'"{_imap_escape(msg.subject)}"' if msg.subject else '""'
    from_str = _format_addr(msg.sender)
    to_str = _format_addr(msg.to)
    msg_id = f'"<{msg.uid}@fakemail.local>"'
    return f"({date_str} {subj_str} {from_str} {from_str} NIL {to_str} NIL NIL NIL {msg_id})"


def _filter_headers(raw_bytes: bytes, field_names: list[str]) -> bytes:
    """Extract requested header fields from raw message bytes."""
    header_bytes, _, _ = raw_bytes.partition(b"\r\n\r\n")
    if not header_bytes:
        header_bytes, _, _ = raw_bytes.partition(b"\n\n")
    msg = email.message_from_bytes(header_bytes, policy=email.policy.default)
    wanted = {f.lower() for f in field_names}
    lines = []
    for k, v in msg.items():
        if k.lower() in wanted:
            lines.append(f"{k}: {v}\r\n".encode("utf-8"))
    return b"".join(lines) + b"\r\n"


def _parse_msg_set(spec: str, max_count: int) -> list[int]:
    """Parse an IMAP sequence set like '1', '1:3', '1,3', or '*'."""
    seqs: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            start_str, _, end_str = part.partition(":")
            start = max_count if start_str == "*" else int(start_str)
            end = max_count if end_str == "*" else int(end_str)
            step = 1 if start <= end else -1
            for n in range(start, end + step, step):
                if 1 <= n <= max_count and n not in seqs:
                    seqs.append(n)
        elif part == "*":
            if max_count >= 1 and max_count not in seqs:
                seqs.append(max_count)
        elif part.isdigit():
            n = int(part)
            if 1 <= n <= max_count and n not in seqs:
                seqs.append(n)
    return seqs


def _match_search(msg: ImapMessage, tokens: list[str]) -> bool:
    """Check if an IMAP message matches all search tokens.

    Raises ValueError for an unsupported keyword or a missing argument, so the
    server can answer BAD instead of silently returning a wrong result.
    """
    text_fields = {
        "FROM": lambda m: m.sender,
        "TO": lambda m: m.to,
        "SUBJECT": lambda m: m.subject,
        "BODY": lambda m: m.body,
        "TEXT": lambda m: m.body + "\n" + m.raw.decode("utf-8", "replace"),
    }
    matched = True
    i = 0
    while i < len(tokens):
        token = tokens[i].upper()
        if token == "ALL":
            i += 1
        elif token in ("SEEN", "UNSEEN"):
            if (r"\Seen" in msg.flags) != (token == "SEEN"):
                matched = False
            i += 1
        elif token in text_fields:
            if i + 1 >= len(tokens):
                raise ValueError(f"{token} needs an argument")
            if tokens[i + 1].strip('"').lower() not in text_fields[token](msg).lower():
                matched = False
            i += 2
        else:
            raise ValueError(f"unsupported search criterion {tokens[i]}")
        # keep scanning after a mismatch so bad criteria later in the query still raise
    return matched


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Threaded TCP server that reuses addresses and closes cleanly."""

    allow_reuse_address = True
    daemon_threads = True
    mail_server: "FakeMailServer"


class SmtpHandler(socketserver.StreamRequestHandler):
    """Minimal SMTP handler supporting HELO/EHLO, AUTH, MAIL, RCPT, DATA, RSET, QUIT."""

    def handle(self) -> None:
        self.wfile.write(b"220 127.0.0.1 FakeMail SMTP ready\r\n")
        self.wfile.flush()

        sender: str | None = None
        recipients: list[str] = []

        while True:
            line_bytes = self.rfile.readline()
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8", "replace").strip("\r\n")
            if not line:
                continue

            cmd, _, arg = line.partition(" ")
            cmd = cmd.strip().upper()
            arg = arg.strip()

            if cmd == "HELO":
                self.wfile.write(b"250 127.0.0.1\r\n")
            elif cmd == "EHLO":
                self.wfile.write(b"250-127.0.0.1\r\n250-AUTH PLAIN LOGIN\r\n250-8BITMIME\r\n250 SIZE 10485760\r\n")
            elif cmd == "AUTH":
                sub = arg.upper()
                if sub.startswith("PLAIN"):
                    b64_token = arg[5:].strip()
                    if not b64_token:
                        self.wfile.write(b"334 \r\n")
                        self.wfile.flush()
                        b64_token = self.rfile.readline().decode("utf-8", "replace").strip()
                    try:
                        decoded = base64.b64decode(b64_token.encode("ascii"))
                        parts = decoded.split(b"\x00")
                        user = parts[1].decode("utf-8") if len(parts) > 1 else ""
                        pwd = parts[2].decode("utf-8") if len(parts) > 2 else ""
                        if user == TEST_USER and pwd == TEST_PASSWORD:
                            self.wfile.write(b"235 2.7.0 Authentication successful\r\n")
                        else:
                            self.wfile.write(b"535 5.7.8 Authentication credentials invalid\r\n")
                    except Exception:
                        self.wfile.write(b"535 5.7.8 Authentication credentials invalid\r\n")
                elif sub.startswith("LOGIN"):
                    self.wfile.write(b"334 VXNlcm5hbWU6\r\n")  # Username:
                    self.wfile.flush()
                    user_b64 = self.rfile.readline().decode("utf-8", "replace").strip()
                    self.wfile.write(b"334 UGFzc3dvcmQ6\r\n")  # Password:
                    self.wfile.flush()
                    pwd_b64 = self.rfile.readline().decode("utf-8", "replace").strip()
                    try:
                        user = base64.b64decode(user_b64.encode("ascii")).decode("utf-8")
                        pwd = base64.b64decode(pwd_b64.encode("ascii")).decode("utf-8")
                        if user == TEST_USER and pwd == TEST_PASSWORD:
                            self.wfile.write(b"235 2.7.0 Authentication successful\r\n")
                        else:
                            self.wfile.write(b"535 5.7.8 Authentication credentials invalid\r\n")
                    except Exception:
                        self.wfile.write(b"535 5.7.8 Authentication credentials invalid\r\n")
                else:
                    self.wfile.write(b"504 5.5.4 Unrecognized authentication mechanism\r\n")
            elif cmd == "MAIL":
                addr = arg
                if addr.upper().startswith("FROM:"):
                    addr = addr[5:].strip()
                if "<" in addr and ">" in addr:
                    addr = addr.partition("<")[2].partition(">")[0].strip()
                else:
                    addr = addr.split()[0].strip("<> ") if addr.split() else ""
                sender = addr
                recipients = []
                self.wfile.write(b"250 2.1.0 OK\r\n")
            elif cmd == "RCPT":
                addr = arg
                if addr.upper().startswith("TO:"):
                    addr = addr[3:].strip()
                if "<" in addr and ">" in addr:
                    addr = addr.partition("<")[2].partition(">")[0].strip()
                else:
                    addr = addr.split()[0].strip("<> ") if addr.split() else ""
                if addr.lower().startswith("reject@"):
                    self.wfile.write(b"550 5.1.1 User unknown\r\n")
                else:
                    recipients.append(addr)
                    self.wfile.write(b"250 2.1.5 OK\r\n")
            elif cmd == "DATA":
                if not recipients:
                    self.wfile.write(b"503 5.5.1 Error: need RCPT command\r\n")
                    self.wfile.flush()
                    continue
                self.wfile.write(b"354 Start mail input; end with <CRLF>.<CRLF>\r\n")
                self.wfile.flush()

                data_lines: list[str] = []
                while True:
                    dline = self.rfile.readline()
                    if not dline:
                        break
                    decoded_line = dline.decode("utf-8", "replace")
                    if decoded_line == ".\r\n" or decoded_line == ".\n":
                        break
                    if decoded_line.startswith(".."):
                        decoded_line = decoded_line[1:]
                    data_lines.append(decoded_line)

                raw_msg = "".join(data_lines)
                raw_hdr, _, body = raw_msg.partition("\r\n\r\n")
                if not _:
                    raw_hdr, _, body = raw_msg.partition("\n\n")

                parsed = email.message_from_string(raw_msg)
                headers = dict(parsed.items())
                subject = parsed.get("Subject", "")

                msg_record = SmtpMessage(
                    sender=sender or "",
                    recipients=list(recipients),
                    raw=raw_msg,
                    raw_headers=raw_hdr,
                    body=body,
                    headers=headers,
                    subject=subject,
                )
                self.server.mail_server._record_smtp_message(msg_record)
                sender = None
                recipients = []
                self.wfile.write(b"250 2.0.0 OK: message queued\r\n")
            elif cmd == "RSET":
                sender = None
                recipients = []
                self.wfile.write(b"250 2.0.0 OK\r\n")
            elif cmd == "NOOP":
                self.wfile.write(b"250 2.0.0 OK\r\n")
            elif cmd == "QUIT":
                self.wfile.write(b"221 2.0.0 Bye\r\n")
                self.wfile.flush()
                break
            else:
                self.wfile.write(b"500 5.5.2 Command unrecognized\r\n")
            self.wfile.flush()


class ImapHandler(socketserver.StreamRequestHandler):
    """Minimal IMAP4rev1 handler supporting LOGIN, LIST, SELECT, SEARCH, FETCH, STORE, APPEND, LOGOUT."""

    def handle(self) -> None:
        self.wfile.write(b"* OK [CAPABILITY IMAP4rev1] FakeMail IMAP ready\r\n")
        self.wfile.flush()

        authenticated = False
        selected_mailbox: str | None = None

        while True:
            line_bytes = self.rfile.readline()
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8", "replace").strip("\r\n")
            if not line:
                continue

            parts = line.split(None, 2)
            tag = parts[0]
            cmd = parts[1].upper() if len(parts) > 1 else ""
            args = parts[2] if len(parts) > 2 else ""

            if cmd == "CAPABILITY":
                self.wfile.write(f"* CAPABILITY IMAP4rev1\r\n{tag} OK CAPABILITY completed\r\n".encode())
            elif cmd == "NOOP":
                self.wfile.write(f"{tag} OK NOOP completed\r\n".encode())
            elif cmd == "LOGIN":
                try:
                    tokens = shlex.split(args)
                    user = tokens[0] if tokens else ""
                    pwd = tokens[1] if len(tokens) > 1 else ""
                except Exception:
                    tokens = args.split()
                    user = tokens[0] if tokens else ""
                    pwd = tokens[1] if len(tokens) > 1 else ""
                if user == TEST_USER and pwd == TEST_PASSWORD:
                    authenticated = True
                    self.wfile.write(f"{tag} OK LOGIN completed\r\n".encode())
                else:
                    self.wfile.write(f"{tag} NO [AUTHENTICATIONFAILED] Invalid credentials\r\n".encode())
            elif cmd == "LIST":
                if not authenticated:
                    self.wfile.write(f"{tag} NO Must authenticate first\r\n".encode())
                else:
                    for mbox in self.server.mail_server._list_mailboxes():
                        self.wfile.write(f'* LIST (\\HasNoChildren) "/" "{mbox}"\r\n'.encode())
                    self.wfile.write(f"{tag} OK LIST completed\r\n".encode())
            elif cmd in ("SELECT", "EXAMINE"):
                if not authenticated:
                    self.wfile.write(f"{tag} NO Must authenticate first\r\n".encode())
                else:
                    target_name = args.strip('" ')
                    actual = self.server.mail_server._get_mailbox_name(target_name)
                    if actual is not None:
                        selected_mailbox = actual
                        msgs = self.server.mail_server.mailboxes[selected_mailbox]
                        count = len(msgs)
                        mode = "READ-ONLY" if cmd == "EXAMINE" else "READ-WRITE"
                        self.wfile.write(f"* {count} EXISTS\r\n".encode())
                        self.wfile.write(b"* 0 RECENT\r\n")
                        self.wfile.write(b"* FLAGS (\\Seen \\Answered \\Flagged \\Deleted \\Draft \\Recent)\r\n")
                        self.wfile.write(b"* OK [PERMANENTFLAGS (\\Seen \\Answered \\Flagged \\Deleted \\Draft \\*)] Limited\r\n")
                        self.wfile.write(b"* OK [UIDVALIDITY 1] UIDs valid\r\n")
                        next_uid = self.server.mail_server._next_uid
                        self.wfile.write(f"* OK [UIDNEXT {next_uid}] Predicted next UID\r\n".encode())
                        self.wfile.write(f"{tag} OK [{mode}] {cmd} completed\r\n".encode())
                    else:
                        self.wfile.write(f"{tag} NO [NONEXISTENT] Mailbox does not exist\r\n".encode())
            elif cmd == "SEARCH":
                if not authenticated or selected_mailbox is None:
                    self.wfile.write(f"{tag} NO No mailbox selected\r\n".encode())
                else:
                    search_str = args
                    if search_str.upper().startswith("CHARSET UTF-8 "):
                        search_str = search_str[14:].strip()
                    try:
                        tokens = shlex.split(search_str.replace("(", " ").replace(")", " "))
                    except Exception:
                        tokens = search_str.replace("(", " ").replace(")", " ").split()

                    msgs = self.server.mail_server.mailboxes[selected_mailbox]
                    try:
                        matches = [idx + 1 for idx, m in enumerate(msgs) if _match_search(m, tokens)]
                    except ValueError as exc:
                        self.wfile.write(f"{tag} BAD {exc}\r\n".encode())
                        continue
                    if matches:
                        res_str = " ".join(str(m) for m in matches)
                        self.wfile.write(f"* SEARCH {res_str}\r\n".encode())
                    else:
                        self.wfile.write(b"* SEARCH\r\n")
                    self.wfile.write(f"{tag} OK SEARCH completed\r\n".encode())
            elif cmd == "FETCH":
                if not authenticated or selected_mailbox is None:
                    self.wfile.write(f"{tag} NO No mailbox selected\r\n".encode())
                else:
                    spec, _, fetch_items_raw = args.partition(" ")
                    fetch_items_upper = fetch_items_raw.upper()
                    msgs = self.server.mail_server.mailboxes[selected_mailbox]
                    seqs = _parse_msg_set(spec, len(msgs))

                    for seq in seqs:
                        msg = msgs[seq - 1]
                        responses: list[bytes] = []

                        # Flags
                        flag_str = " ".join(sorted(msg.flags))
                        flags_item = f"FLAGS ({flag_str})".encode()

                        if "ENVELOPE" in fetch_items_upper:
                            env = _format_envelope(msg)
                            responses.append(f"ENVELOPE {env}".encode())

                        if "RFC822.SIZE" in fetch_items_upper:
                            responses.append(f"RFC822.SIZE {len(msg.raw)}".encode())

                        if "UID" in fetch_items_upper:
                            responses.append(f"UID {msg.uid}".encode())

                        if "BODY.PEEK[HEADER.FIELDS" in fetch_items_upper or "BODY[HEADER.FIELDS" in fetch_items_upper:
                            m = re.search(r"BODY(?:\.PEEK)?\[HEADER\.FIELDS\s*\(([^)]+)\)\]", fetch_items_raw, re.IGNORECASE)
                            fields_list = m.group(1).split() if m else []
                            hdr_bytes = _filter_headers(msg.raw, fields_list)
                            item_name = m.group(0).replace(".PEEK", "") if m else "BODY[HEADER]"
                            responses.append(f"{item_name} {{{len(hdr_bytes)}}}\r\n".encode() + hdr_bytes)
                        elif "BODY.PEEK[HEADER]" in fetch_items_upper or "BODY[HEADER]" in fetch_items_upper:
                            hdr_bytes, _, _ = msg.raw.partition(b"\r\n\r\n")
                            if not _:
                                hdr_bytes, _, _ = msg.raw.partition(b"\n\n")
                            hdr_bytes = hdr_bytes + b"\r\n\r\n"
                            responses.append(f"BODY[HEADER] {{{len(hdr_bytes)}}}\r\n".encode() + hdr_bytes)
                        elif "BODY.PEEK[TEXT]" in fetch_items_upper or "BODY[TEXT]" in fetch_items_upper:
                            body_bytes = msg.body.encode("utf-8")
                            responses.append(f"BODY[TEXT] {{{len(body_bytes)}}}\r\n".encode() + body_bytes)
                        elif "RFC822" in fetch_items_upper or "BODY[]" in fetch_items_upper or "BODY.PEEK[]" in fetch_items_upper:
                            responses.append(f"RFC822 {{{len(msg.raw)}}}\r\n".encode() + msg.raw)

                        if "FLAGS" in fetch_items_upper or not responses:
                            flag_str = " ".join(sorted(msg.flags))
                            flags_item = f"FLAGS ({flag_str})".encode()
                            responses.insert(0, flags_item)

                        combined = b" ".join(responses)
                        self.wfile.write(f"* {seq} FETCH ({combined.decode('utf-8', 'replace')})\r\n".encode())

                    self.wfile.write(f"{tag} OK FETCH completed\r\n".encode())
            elif cmd == "STORE":
                if not authenticated or selected_mailbox is None:
                    self.wfile.write(f"{tag} NO No mailbox selected\r\n".encode())
                else:
                    store_parts = args.split(None, 2)
                    spec = store_parts[0] if store_parts else ""
                    subcmd = store_parts[1].upper() if len(store_parts) > 1 else ""
                    raw_flags = store_parts[2] if len(store_parts) > 2 else ""
                    flag_tokens = raw_flags.strip("() ").split()

                    msgs = self.server.mail_server.mailboxes[selected_mailbox]
                    seqs = _parse_msg_set(spec, len(msgs))
                    silent = ".SILENT" in subcmd

                    for seq in seqs:
                        msg = msgs[seq - 1]
                        if subcmd.startswith("+FLAGS"):
                            msg.flags.update(flag_tokens)
                        elif subcmd.startswith("-FLAGS"):
                            msg.flags.difference_update(flag_tokens)
                        elif subcmd.startswith("FLAGS"):
                            msg.flags = set(flag_tokens)

                        if not silent:
                            flag_str = " ".join(sorted(msg.flags))
                            self.wfile.write(f"* {seq} FETCH (FLAGS ({flag_str}))\r\n".encode())

                    self.wfile.write(f"{tag} OK STORE completed\r\n".encode())
            elif cmd == "APPEND":
                if not authenticated:
                    self.wfile.write(f"{tag} NO Must authenticate first\r\n".encode())
                else:
                    m = re.search(r"\{(\d+)\}$", args)
                    size = int(m.group(1)) if m else 0
                    prefix = args[:m.start()].strip() if m else args

                    # Parse mailbox and optional flags
                    tokens = prefix.split(None, 1)
                    target_mailbox = tokens[0].strip('"') if tokens else "INBOX"
                    actual_mbox = self.server.mail_server._get_mailbox_name(target_mailbox) or target_mailbox

                    flags: set[str] = set()
                    if len(tokens) > 1 and "(" in tokens[1]:
                        flags_match = re.search(r"\(([^)]*)\)", tokens[1])
                        if flags_match:
                            flags = set(flags_match.group(1).split())

                    self.wfile.write(b"+ Ready for literal data\r\n")
                    self.wfile.flush()

                    raw_literal = self.rfile.read(size)
                    # Consume any trailing CRLF
                    self.rfile.readline()

                    self.server.mail_server._append_raw_message(actual_mbox, raw_literal, flags)
                    self.wfile.write(f"{tag} OK APPEND completed\r\n".encode())
            elif cmd in ("CLOSE", "EXPUNGE"):
                if not authenticated or selected_mailbox is None:
                    self.wfile.write(f"{tag} NO No mailbox selected\r\n".encode())
                else:
                    msgs = self.server.mail_server.mailboxes[selected_mailbox]
                    retained: list[ImapMessage] = []
                    for idx, m in enumerate(msgs):
                        if r"\Deleted" in m.flags:
                            if cmd == "EXPUNGE":
                                self.wfile.write(f"* {idx + 1} EXPUNGE\r\n".encode())
                        else:
                            retained.append(m)
                    self.server.mail_server.mailboxes[selected_mailbox] = retained
                    if cmd == "CLOSE":
                        selected_mailbox = None
                    self.wfile.write(f"{tag} OK {cmd} completed\r\n".encode())
            elif cmd == "LOGOUT":
                self.wfile.write(b"* BYE FakeMail IMAP server terminating connection\r\n")
                self.wfile.write(f"{tag} OK LOGOUT completed\r\n".encode())
                self.wfile.flush()
                break
            else:
                self.wfile.write(f"{tag} BAD Command unrecognized or not implemented\r\n".encode())
            self.wfile.flush()


class FakeMailServer:
    """In-memory SMTP and IMAP test server running on 127.0.0.1 only."""

    def __init__(self, smtp_port: int = 0, imap_port: int = 0) -> None:
        self.smtp_port = smtp_port
        self.imap_port = imap_port
        self.smtp_messages: list[SmtpMessage] = []
        self.mailboxes: dict[str, list[ImapMessage]] = {
            "INBOX": [],
            "Drafts": [],
        }
        self._next_uid = 1
        self._lock = threading.RLock()
        self._smtp_server: ThreadedTCPServer | None = None
        self._imap_server: ThreadedTCPServer | None = None
        self._smtp_thread: threading.Thread | None = None
        self._imap_thread: threading.Thread | None = None

    def start(self) -> "FakeMailServer":
        """Start both SMTP and IMAP servers on 127.0.0.1."""
        self._smtp_server = ThreadedTCPServer((HOST, self.smtp_port), SmtpHandler)
        self._smtp_server.mail_server = self
        self.smtp_port = self._smtp_server.server_address[1]

        self._imap_server = ThreadedTCPServer((HOST, self.imap_port), ImapHandler)
        self._imap_server.mail_server = self
        self.imap_port = self._imap_server.server_address[1]

        self._smtp_thread = threading.Thread(target=self._smtp_server.serve_forever, daemon=True)
        self._smtp_thread.start()

        self._imap_thread = threading.Thread(target=self._imap_server.serve_forever, daemon=True)
        self._imap_thread.start()
        return self

    def stop(self) -> None:
        """Stop both servers and close listening sockets."""
        if self._smtp_server:
            self._smtp_server.shutdown()
            self._smtp_server.server_close()
            self._smtp_server = None
        if self._imap_server:
            self._imap_server.shutdown()
            self._imap_server.server_close()
            self._imap_server = None
        if self._smtp_thread:
            self._smtp_thread.join(timeout=2.0)
            self._smtp_thread = None
        if self._imap_thread:
            self._imap_thread.join(timeout=2.0)
            self._imap_thread = None

    def __enter__(self) -> "FakeMailServer":
        self.start()
        return self

    def __exit__(self, *args) -> None:
        self.stop()

    def reset(self) -> None:
        """Clear recorded messages and reset mailboxes."""
        with self._lock:
            self.smtp_messages.clear()
            self.mailboxes = {"INBOX": [], "Drafts": []}
            self._next_uid = 1

    def _record_smtp_message(self, msg: SmtpMessage) -> None:
        with self._lock:
            self.smtp_messages.append(msg)

    def _list_mailboxes(self) -> list[str]:
        with self._lock:
            return list(self.mailboxes.keys())

    def _get_mailbox_name(self, name: str) -> str | None:
        with self._lock:
            for k in self.mailboxes:
                if k.lower() == name.lower():
                    return k
        return None

    def add_message(
        self,
        mailbox: str = "INBOX",
        sender: str = "sender@example.com",
        to: str = "recipient@example.com",
        subject: str = "Test Subject",
        body: str = "Test Body",
        flags: set[str] | list[str] | None = None,
        date: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> ImapMessage:
        """Seed a message into an IMAP mailbox from Python."""
        with self._lock:
            actual_mbox = self._get_mailbox_name(mailbox) or mailbox
            if actual_mbox not in self.mailboxes:
                self.mailboxes[actual_mbox] = []

            uid = self._next_uid
            self._next_uid += 1
            date_val = date or email.utils.formatdate(localtime=True)
            all_headers = {
                "From": sender,
                "To": to,
                "Subject": subject,
                "Date": date_val,
                "Message-ID": f"<{uid}@fakemail.local>",
                "Content-Type": 'text/plain; charset="utf-8"',
            }
            if headers:
                all_headers.update(headers)

            hdr_lines = [f"{k}: {v}\r\n" for k, v in all_headers.items()]
            raw_bytes = ("".join(hdr_lines) + "\r\n" + body).encode("utf-8")

            msg = ImapMessage(
                uid=uid,
                sender=sender,
                to=to,
                subject=subject,
                body=body,
                date=date_val,
                headers=all_headers,
                raw=raw_bytes,
                flags=set(flags or []),
            )
            self.mailboxes[actual_mbox].append(msg)
            return msg

    def _append_raw_message(self, mailbox: str, raw_bytes: bytes, flags: set[str]) -> ImapMessage:
        with self._lock:
            if mailbox not in self.mailboxes:
                self.mailboxes[mailbox] = []

            uid = self._next_uid
            self._next_uid += 1

            parsed = email.message_from_bytes(raw_bytes, policy=email.policy.default)
            sender = parsed.get("From", "")
            to = parsed.get("To", "")
            subject = parsed.get("Subject", "")
            date_val = parsed.get("Date", "") or email.utils.formatdate(localtime=True)
            body = parsed.get_body(preferencelist=("plain",)).get_content() if parsed.is_multipart() else parsed.get_payload()
            if not isinstance(body, str):
                body = str(body)

            msg = ImapMessage(
                uid=uid,
                sender=sender,
                to=to,
                subject=subject,
                body=body,
                date=date_val,
                headers=dict(parsed.items()),
                raw=raw_bytes,
                flags=set(flags),
            )
            self.mailboxes[mailbox].append(msg)
            return msg


if __name__ == "__main__":
    smtp_p = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SMTP_PORT
    imap_p = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_IMAP_PORT
    server = FakeMailServer(smtp_port=smtp_p, imap_port=imap_p)
    server.start()
    print(f"FakeMail running on {HOST} (SMTP {server.smtp_port}, IMAP {server.imap_port}). Press Ctrl-C to stop.", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping FakeMail...")
    finally:
        server.stop()
