#!/usr/bin/env python3
# ==========================================================================
# Smart 2FA Manager - independent TOTP generator
# Version: v1.1.0
# Author: Alexander Suvorov
# Repository: https://github.com/smartlegionlab/smart-2fa-manager-cli
# License: BSD 3-Clause
# ==========================================================================
import sys
import subprocess
import getpass
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict

CONFIG_DIR = Path.home() / ".2fa"
SECRETS_ENC = CONFIG_DIR / "secrets.gpg"
SECRETS_TMP = CONFIG_DIR / "secrets.tmp"
BACKUP_DIR = CONFIG_DIR / "backups"
VERSION = "v1.1.0"

RED = '\033[0;31m'
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
BLUE = '\033[0;34m'
NC = '\033[0m'

APP_NAME = "Smart 2FA Manager"

CONFIG_DIR.mkdir(exist_ok=True)
BACKUP_DIR.mkdir(exist_ok=True)


def print_color(text: str, color: str = NC, end: str = '\n'):
    print(f"{color}{text}{NC}", end=end)


def sanitize_service_name(name: str) -> Optional[str]:
    name = name.replace(' ', '_')
    name = re.sub(r'[^a-zA-Z0-9_-]', '', name)
    name = name.lower()
    return name if name else None


def get_gpg_pass(prompt: str = "Enter password: ") -> str:
    return getpass.getpass(prompt)


def decrypt_store(password: str) -> Optional[str]:
    if not SECRETS_ENC.exists():
        print_color("Storage does not exist. Run '2fa init'", YELLOW)
        return None

    try:
        result = subprocess.run(
            ['gpg', '--batch', '--yes', '--passphrase', password,
             '--decrypt', str(SECRETS_ENC)],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print_color("[ERR] Wrong password or corrupted storage", RED)
            return None

        SECRETS_TMP.write_text(result.stdout)
        return result.stdout
    except Exception as e:
        print_color(f"[ERR] Decryption failed: {e}", RED)
        return None


def encrypt_store(password: str, content: str = None) -> bool:
    try:
        if content is not None:
            SECRETS_TMP.write_text(content)

        if not SECRETS_TMP.exists():
            return False

        result = subprocess.run(
            ['gpg', '--batch', '--yes', '--passphrase', password,
             '--symmetric', '--cipher-algo', 'AES256',
             '--output', str(SECRETS_ENC), str(SECRETS_TMP)],
            capture_output=True
        )

        SECRETS_TMP.unlink(missing_ok=True)

        if result.returncode != 0:
            print_color("[ERR] Error during encryption", RED)
            return False
        return True
    except Exception as e:
        print_color(f"[ERR] Encryption failed: {e}", RED)
        return False


def load_secrets(password: str) -> Optional[Dict[str, str]]:
    content = decrypt_store(password)
    if content is None:
        return None

    secrets = {}
    for line in content.strip().split('\n'):
        if ':' in line:
            service, secret = line.split(':', 1)
            secrets[service.strip()] = secret.strip()
    return secrets


def save_secrets(password: str, secrets: Dict[str, str]) -> bool:
    content = '\n'.join([f"{k}:{v}" for k, v in sorted(secrets.items())])
    if content:
        content += '\n'
    return encrypt_store(password, content)


def generate_totp(secret: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ['oathtool', '--totp', '-b', secret],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            print_color("[ERR] Code generation failed. Is the secret correct?", RED)
            return None
    except FileNotFoundError:
        print_color("[ERR] oathtool not installed. Install it: sudo apt install oathtool", RED)
        return None


def copy_to_clipboard(text: str) -> bool:
    if subprocess.run(['which', 'xclip'], capture_output=True).returncode == 0:
        proc = subprocess.run(['xclip', '-selection', 'clipboard'],
                              input=text, text=True, capture_output=True)
        return proc.returncode == 0
    elif subprocess.run(['which', 'wl-copy'], capture_output=True).returncode == 0:
        proc = subprocess.run(['wl-copy'], input=text, text=True, capture_output=True)
        return proc.returncode == 0
    return False


def cmd_init():
    if SECRETS_ENC.exists():
        print_color("Storage already exists. Overwrite? (y/N)", YELLOW, end=' ')
        ans = input().lower()
        if ans != 'y':
            return

    password = get_gpg_pass("Create password: ")
    password2 = get_gpg_pass("Repeat password: ")

    if password != password2:
        print_color("[ERR] Passwords do not match", RED)
        sys.exit(1)

    if save_secrets(password, {}):
        print_color(f"[OK] Storage created at {SECRETS_ENC}", GREEN)


def cmd_add(service: str, secret: str):
    if not service or not secret:
        print_color("[ERR] Usage: 2fa add <service> <secret>", RED)
        sys.exit(1)

    service = sanitize_service_name(service)
    if not service:
        print_color("[ERR] Service name contains no valid characters (a-z, 0-9, _, -)", RED)
        sys.exit(1)

    secret = re.sub(r'\s', '', secret).upper()
    password = get_gpg_pass()

    secrets = load_secrets(password)
    if secrets is None:
        sys.exit(1)

    if service in secrets:
        print_color(f"[WARN] Service '{service}' already exists. Replace? (y/N)", YELLOW, end=' ')
        ans = input().lower()
        if ans != 'y':
            return

    secrets[service] = secret
    if save_secrets(password, secrets):
        print_color(f"[OK] {APP_NAME}: Service '{service}' added successfully", GREEN)


def cmd_get(service: str):
    if not service:
        print_color("[ERR] Usage: 2fa get <service>", RED)
        sys.exit(1)

    service = sanitize_service_name(service)
    if not service:
        print_color("[ERR] Invalid service name", RED)
        sys.exit(1)

    password = get_gpg_pass()
    secrets = load_secrets(password)
    if secrets is None:
        sys.exit(1)

    if service not in secrets:
        print_color(f"[ERR] Service '{service}' not found", RED)
        sys.exit(1)

    code = generate_totp(secrets[service])
    if code:
        print_color(f"{APP_NAME} - TOTP for ", end='')
        print_color(f"{service}", GREEN, end='')
        print_color(f": {code}", YELLOW)

        if copy_to_clipboard(code):
            print_color("[OK] Copied to clipboard", YELLOW)


def cmd_list():
    password = get_gpg_pass()
    secrets = load_secrets(password)
    if secrets is None:
        sys.exit(1)

    count = len(secrets)
    print_color(f"{APP_NAME} - Saved services ({count}):", BLUE)
    for service in sorted(secrets.keys()):
        print(f"  - {service}")


def cmd_show_all():
    password = get_gpg_pass()
    secrets = load_secrets(password)
    if secrets is None:
        sys.exit(1)

    print_color(f"{APP_NAME} - All services with current codes", BLUE)
    print_color("========================================", GREEN)

    total = 0
    for service in sorted(secrets.keys()):
        code = generate_totp(secrets[service])
        if code:
            print_color(f"  {service:<20}", GREEN, end='')
            print_color(f" : {code}", YELLOW)
            total += 1
        else:
            print_color(f"  {service:<20}", RED, end='')
            print_color(" : [ERR] invalid secret", RED)

    print_color("========================================", GREEN)
    print_color(f"[OK] Total: {total} service(s)", GREEN)


def cmd_del(service: str):
    if not service:
        print_color("[ERR] Usage: 2fa del <service>", RED)
        sys.exit(1)

    service = sanitize_service_name(service)
    if not service:
        print_color("[ERR] Invalid service name", RED)
        sys.exit(1)

    password = get_gpg_pass()
    secrets = load_secrets(password)
    if secrets is None:
        sys.exit(1)

    if service not in secrets:
        print_color(f"[ERR] Service '{service}' not found", RED)
        sys.exit(1)

    del secrets[service]
    if save_secrets(password, secrets):
        print_color(f"[OK] {APP_NAME}: Service '{service}' deleted successfully", GREEN)


def cmd_show():
    password = get_gpg_pass()
    content = decrypt_store(password)
    if content is None:
        sys.exit(1)

    print_color(f"[WARN] {APP_NAME} - Unencrypted content (DO NOT SHOW ANYONE)", YELLOW)
    print_color("==============================================", YELLOW)
    print(content, end='')
    print_color("==============================================", YELLOW)


def cmd_backup():
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_file = BACKUP_DIR / f"secrets.{timestamp}.gpg"

    print_color(f"{APP_NAME} - Creating backup", BLUE)
    password = get_gpg_pass()

    content = decrypt_store(password)
    if content is None:
        sys.exit(1)

    try:
        result = subprocess.run(
            ['gpg', '--batch', '--yes', '--passphrase', password,
             '--symmetric', '--cipher-algo', 'AES256',
             '--output', str(backup_file), str(SECRETS_TMP)],
            capture_output=True
        )
        SECRETS_TMP.unlink(missing_ok=True)

        if result.returncode != 0:
            print_color("[ERR] Error creating backup", RED)
            sys.exit(1)

        print_color(f"[OK] Backup saved: {backup_file}", GREEN)
    except Exception as e:
        print_color(f"[ERR] Backup failed: {e}", RED)
        sys.exit(1)


def cmd_restore(backup_file: str):
    backup_path = Path(backup_file)
    if not backup_path.exists():
        print_color(f"[ERR] File not found: {backup_file}", RED)
        sys.exit(1)

    print_color(f"{APP_NAME} - Restoring from backup", BLUE)
    password = get_gpg_pass("Enter password for backup: ")

    try:
        result = subprocess.run(
            ['gpg', '--batch', '--yes', '--passphrase', password,
             '--decrypt', str(backup_path)],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print_color("[ERR] Wrong password or corrupted backup", RED)
            sys.exit(1)

        content = result.stdout
        if ':' not in content:
            print_color("[ERR] Invalid backup format (expected service:secret)", RED)
            sys.exit(1)

        count = len([l for l in content.split('\n') if l.strip()])

        new_password = get_gpg_pass("Create new password for restored storage: ")
        new_password2 = get_gpg_pass("Repeat new password: ")

        if new_password != new_password2:
            print_color("[ERR] Passwords do not match", RED)
            sys.exit(1)

        if encrypt_store(new_password, content):
            print_color(f"[OK] Restored {count} entries successfully", GREEN)
    except Exception as e:
        print_color(f"[ERR] Restore failed: {e}", RED)
        sys.exit(1)


def cmd_qr(service: str):
    if not service:
        print_color("[ERR] Usage: 2fa qr <service>", RED)
        sys.exit(1)

    service = sanitize_service_name(service)
    if not service:
        print_color("[ERR] Invalid service name", RED)
        sys.exit(1)

    password = get_gpg_pass()
    secrets = load_secrets(password)
    if secrets is None:
        sys.exit(1)

    if service not in secrets:
        print_color(f"[ERR] Service '{service}' not found", RED)
        sys.exit(1)

    uri = f"otpauth://totp/{service}?secret={secrets[service]}&issuer=Smart2FA"
    print_color(f"{APP_NAME} - QR code for {service}", BLUE)

    if subprocess.run(['which', 'qrencode'], capture_output=True).returncode == 0:
        subprocess.run(['qrencode', '-t', 'utf8', uri])
        print_color("[OK] Scan this QR code in your authenticator app", YELLOW)
    else:
        print_color("[WARN] qrencode not installed. Install it: sudo apt install qrencode", YELLOW)
        print(f"Manual URI: {uri}")


def about():
    print(f"""
Smart 2FA Manager {VERSION}

Author:  Alexander Suvorov
License: BSD 3-Clause
Repository: https://github.com/smartlegionlab/smart-2fa-manager-python

Description:
    A lightweight, offline, and independent TOTP 2FA manager for Linux.
    No cloud, no phone required. Store your secrets locally, generate codes,
    create encrypted backups, and sync with Google Authenticator via QR codes.

Features:
    - No internet connection required
    - AES-256 encryption via GPG
    - Encrypted timestamped backups
    - QR code export for phone apps
    - Clipboard integration (xclip/wayland)
    - Simple service:secret format

Dependencies:
    - gpg (GNU Privacy Guard)
    - oathtool (OATH Toolkit)
    - qrencode (optional, for QR codes)
    - xclip or wl-copy (optional, for clipboard)

BSD 3-Clause License
    Copyright (c) 2026, Alexander Suvorov
    All rights reserved.
""")


def version():
    print(f"Smart 2FA Manager {VERSION}")


def usage():
    print(f"""
Smart 2FA Manager {VERSION} - Offline TOTP 2FA generator for Linux

Usage:
    2fa.py <command> [arguments]

Commands:
    add <service> <secret>     Add a new service
    get <service>              Get TOTP code (copies to clipboard)
    list                       List all service names
    show-all                   Show all services with current codes
    del <service>              Delete a service
    show                       Show unencrypted content (unsafe)
    backup                     Save encrypted backup with timestamp
    restore <file>             Restore from encrypted backup file
    init                       Initialize storage (create empty)
    qr <service>               Show QR code for phone
    about                      Show author and repository info
    version                    Show version number
    help                       Show this help message

Examples:
    2fa.py init
    2fa.py add github JBSWY3DPEHPK3PXP
    2fa.py get github
    2fa.py list
    2fa.py show-all
    2fa.py qr github
    2fa.py backup
    2fa.py restore ~/.2fa/backups/secrets.2026-04-06.gpg

File Structure:
    ~/.2fa/secrets.gpg          # Encrypted master storage
    ~/.2fa/backups/*.gpg        # Timestamped encrypted backups

Repository: https://github.com/smartlegionlab/smart-2fa-manager-python
License: BSD 3-Clause
""")


def main():
    if len(sys.argv) < 2:
        usage()
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "add":
        if len(sys.argv) < 4:
            print_color("[ERR] Usage: 2fa add <service> <secret>", RED)
            sys.exit(1)
        cmd_add(sys.argv[2], sys.argv[3])
    elif cmd == "get":
        if len(sys.argv) < 3:
            print_color("[ERR] Usage: 2fa get <service>", RED)
            sys.exit(1)
        cmd_get(sys.argv[2])
    elif cmd == "list":
        cmd_list()
    elif cmd == "show-all":
        cmd_show_all()
    elif cmd == "del":
        if len(sys.argv) < 3:
            print_color("[ERR] Usage: 2fa del <service>", RED)
            sys.exit(1)
        cmd_del(sys.argv[2])
    elif cmd == "show":
        cmd_show()
    elif cmd == "backup":
        cmd_backup()
    elif cmd == "restore":
        if len(sys.argv) < 3:
            print_color("[ERR] Usage: 2fa restore <file>", RED)
            sys.exit(1)
        cmd_restore(sys.argv[2])
    elif cmd == "init":
        cmd_init()
    elif cmd == "qr":
        if len(sys.argv) < 3:
            print_color("[ERR] Usage: 2fa qr <service>", RED)
            sys.exit(1)
        cmd_qr(sys.argv[2])
    elif cmd == "about":
        about()
    elif cmd == "version":
        version()
    elif cmd in ["help", "-h", "--help", ""]:
        usage()
    else:
        print_color(f"[ERR] Unknown command: {cmd}", RED)
        usage()
        sys.exit(1)


if __name__ == "__main__":
    main()
