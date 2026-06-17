#!/usr/bin/env python3

import argparse
import sys
from email.message import EmailMessage

from liblore import LoreNode


def payload(message: EmailMessage) -> str:
    body = message.get_body(preferencelist=("plain",))
    if body is None:
        return ""
    return body.get_content().rstrip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch complete public-inbox threads by root message ID"
    )
    parser.add_argument(
        "msgid", nargs="+", help="root message ID without angle brackets"
    )
    parser.add_argument(
        "--node", default="https://lore.kernel.org/all", help="public-inbox endpoint"
    )
    parser.add_argument(
        "--exclude-from",
        action="append",
        default=[],
        help="case-insensitive substring of From headers to omit",
    )
    args = parser.parse_args()

    excludes = [value.casefold() for value in args.exclude_from]
    with LoreNode(args.node) as node:
        for root in args.msgid:
            print(f"# Thread root: <{root}>")
            # liblore's timestamp sorter cannot order a mixture of naive and
            # timezone-aware Received dates, so retain public-inbox order.
            messages = node.get_thread_by_msgid(root, strict=True, sort=False)
            for message in messages:
                sender = str(message.get("From", ""))
                if any(value in sender.casefold() for value in excludes):
                    continue
                print()
                print(f"## {message.get('Subject', '(no subject)')}")
                print()
                print(f"- From: {sender}")
                print(f"- Date: {message.get('Date', '')}")
                print(f"- Message-ID: {message.get('Message-ID', '')}")
                print(f"- In-Reply-To: {message.get('In-Reply-To', '')}")
                print()
                print(payload(message))
            print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
