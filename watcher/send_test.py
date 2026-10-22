import sys

from watcher import config, telegram


def main():
    try:
        secrets = config.load_secrets()
    except config.ConfigError as e:
        print(f"configuration error: {e}", file=sys.stderr)
        sys.exit(1)
    try:
        telegram.send(secrets.token, secrets.chat_id, "itec-watcher: mensagem de teste", html=False)
    except telegram.TelegramError as e:
        print(f"send failed: {e}", file=sys.stderr)
        sys.exit(1)
    print("test message sent")


if __name__ == "__main__":
    main()
