from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence

from . import __version__
from .core import droppedfile, portowner, promptstore, settingsbackup, usagehistory, vault, webdata
from .core.catalog import PROVIDER_IDS
from .core.snapshot import catalog_snapshot, collect_snapshot, detect_snapshot

# Largest applet id or profile generation the plasmoid may pass.
MAX_INT_ARGUMENT = 2**31
_INT_ARGUMENT = re.compile(r"[0-9]{1,10}")
_PORT_ARGUMENT = re.compile(r"[0-9]{1,5}")


def _bounded_int(value: str) -> int:
    """A plain decimal 0..2**31: no sign, spaces, underscores or other digits."""
    if not _INT_ARGUMENT.fullmatch(value) or int(value) > MAX_INT_ARGUMENT:
        raise argparse.ArgumentTypeError("expected an integer from 0 to 2147483648")
    return int(value)


def _port(value: str) -> int:
    """A plain decimal TCP port 1..65535: no sign, spaces, underscores or other digits."""
    if not _PORT_ARGUMENT.fullmatch(value) or not portowner.MIN_PORT <= int(value) <= portowner.MAX_PORT:
        raise argparse.ArgumentTypeError("expected a port from 1 to 65535")
    return int(value)


def _item_id(value: str) -> int:
    """A library item id: a plain decimal 1..2**31."""
    number = _bounded_int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("expected an integer from 1 to 2147483648")
    return number


def _model(value: str) -> str:
    if not promptstore.valid_model(value):
        raise argparse.ArgumentTypeError("expected a model name ([A-Za-z0-9._:/+-], 1 to 200, no leading -)")
    return value


def _hex_path(value: str) -> str:
    if droppedfile.decode_path(value) is None:
        raise argparse.ArgumentTypeError("expected an absolute path as lowercase hex")
    return value


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="hearthwire",
        description="Read local AI CLI sessions and print subscription usage as JSON.",
    )
    result.add_argument("--json", action="store_true", help="Print JSON (the default).")
    result.add_argument(
        "--providers",
        metavar="IDS",
        help="Comma-separated tracked provider IDs.",
    )
    result.add_argument(
        "--catalog",
        action="store_true",
        help="Print the provider catalog without reading credentials or using the network.",
    )
    result.add_argument(
        "--detect",
        action="store_true",
        help="Print the catalog and installed provider IDs without reading credentials or using the network.",
    )
    result.add_argument(
        "--web-data",
        choices=("prepare", "remove", "purge"),
        help="Create or delete a Chat tab profile folder inside the unlocked encrypted folder; "
        "purge deletes the encrypted folder (no network, no credentials).",
    )
    result.add_argument(
        "--store",
        choices=webdata.STORES,
        help="Profile store for --web-data prepare/remove (only 'encrypted').",
    )
    result.add_argument("--applet", type=_bounded_int, metavar="N", help="Applet id for --web-data.")
    result.add_argument("--generation", type=_bounded_int, metavar="G", help="Generation for --web-data prepare.")
    result.add_argument("--keep", type=_bounded_int, metavar="G", help="Generation --web-data remove keeps.")
    result.add_argument(
        "--vault",
        choices=vault.OPERATIONS,
        help="Manage the passphrase-encrypted Chat folder (no network, no credentials).",
    )
    result.add_argument(
        "--method",
        choices=vault.METHODS,
        help="Unlock method for --vault unlock (default passphrase); add-key and remove-key take wallet.",
    )
    result.add_argument(
        "--prompts",
        choices=promptstore.OPERATIONS,
        help="Saved prompts and personas inside the unlocked encrypted folder (no network, no credentials).",
    )
    result.add_argument("--kind", choices=promptstore.KINDS, help="Item kind for --prompts add.")
    result.add_argument("--id", type=_item_id, metavar="N", help="Item id for --prompts replace/remove/set-persona.")
    result.add_argument("--model", type=_model, metavar="NAME", help="Ollama model for --prompts set-persona.")
    result.add_argument("--none", action="store_true", help="Clear the model's persona (--prompts set-persona).")
    result.add_argument(
        "--read-dropped",
        type=_hex_path,
        metavar="HEX",
        help="Print the text of one dropped text file (path as UTF-8 hex; no network, no credentials).",
    )
    result.add_argument(
        "--port-owner",
        type=_port,
        metavar="PORT",
        help="Say whether you, a trusted system account, another user, or nobody listens on "
        "this loopback port (reads /proc/net only; no network, no credentials).",
    )
    result.add_argument(
        "--usage-history",
        choices=usagehistory.OPERATIONS,
        help="Opt-in usage history: read the last 7 days, record one sample, or clear it "
        "(no network, no credentials).",
    )
    result.add_argument(
        "--sample",
        metavar="PAIRS",
        help="provider.metric=PERCENT_USED,... for --usage-history record.",
    )
    result.add_argument(
        "--settings-backup",
        choices=settingsbackup.OPERATIONS,
        help="Settings backup file: status, export or import (no network, no credentials).",
    )
    result.add_argument(
        "--data",
        metavar="HEX",
        help="Settings as lowercase hex of a UTF-8 JSON object, for --settings-backup export.",
    )
    result.add_argument("--version", action="version", version=__version__)
    return result


def _check_prompt_arguments(args: argparse.Namespace, argument_parser: argparse.ArgumentParser) -> None:
    """--kind only for add; --id for replace/remove/set-persona; --model/--none for set-persona."""
    operation = args.prompts
    if operation is None:
        for name, used in (("--kind", args.kind is not None), ("--id", args.id is not None),
                           ("--model", args.model is not None), ("--none", args.none)):
            if used:
                argument_parser.error(f"{name} needs --prompts")
        return
    if (args.kind is not None) != (operation == "add"):
        argument_parser.error("--prompts add needs --kind" if operation == "add" else "--kind is only for --prompts add")
    if operation in ("replace", "remove") and args.id is None:
        argument_parser.error(f"--prompts {operation} needs --id")
    if operation in ("list", "add") and args.id is not None:
        argument_parser.error(f"--id cannot be combined with --prompts {operation}")
    if (args.model is not None) != (operation == "set-persona"):
        argument_parser.error("--prompts set-persona needs --model" if operation == "set-persona"
                              else "--model is only for --prompts set-persona")
    if args.none and operation != "set-persona":
        argument_parser.error("--none is only for --prompts set-persona")
    if operation == "set-persona" and (args.id is None) == (not args.none):
        argument_parser.error("--prompts set-persona needs exactly one of --id and --none")


def _check_history_and_backup_arguments(args: argparse.Namespace, argument_parser: argparse.ArgumentParser) -> None:
    """--sample only and always with --usage-history record; --data likewise with --settings-backup export."""
    if (args.sample is not None) != (args.usage_history == "record"):
        argument_parser.error("--usage-history record needs --sample" if args.usage_history == "record"
                              else "--sample is only for --usage-history record")
    if (args.data is not None) != (args.settings_backup == "export"):
        argument_parser.error("--settings-backup export needs --data" if args.settings_backup == "export"
                              else "--data is only for --settings-backup export")


def _check_helper_arguments(args: argparse.Namespace, argument_parser: argparse.ArgumentParser) -> None:
    """--web-data, --vault, --prompts, --read-dropped, --port-owner, --usage-history and
    --settings-backup stand alone."""
    if args.method is not None and args.vault is None:
        argument_parser.error("--method needs --vault")
    if args.vault is not None:
        if args.method is not None and args.vault not in vault.METHOD_OPERATIONS:
            argument_parser.error(f"--method cannot be combined with --vault {args.vault}")
        if args.vault in ("add-key", "remove-key") and args.method != "wallet":
            argument_parser.error(f"--vault {args.vault} needs --method wallet")
    _check_prompt_arguments(args, argument_parser)
    _check_history_and_backup_arguments(args, argument_parser)
    modes = [
        name for name, used in (
            ("--web-data", args.web_data is not None),
            ("--vault", args.vault is not None),
            ("--prompts", args.prompts is not None),
            ("--read-dropped", args.read_dropped is not None),
            ("--port-owner", args.port_owner is not None),
            ("--usage-history", args.usage_history is not None),
            ("--settings-backup", args.settings_backup is not None),
        ) if used
    ]
    if len(modes) > 1:
        argument_parser.error(f"{modes[0]} and {modes[1]} cannot be combined")
    snapshot_options = [
        name for name, used in (
            ("--json", args.json),
            ("--providers", args.providers is not None),
            ("--catalog", args.catalog),
            ("--detect", args.detect),
        ) if used
    ]
    web_options = [
        name for name, used in (
            ("--store", args.store is not None),
            ("--applet", args.applet is not None),
            ("--generation", args.generation is not None),
            ("--keep", args.keep is not None),
        ) if used
    ]
    if (args.port_owner is not None or args.prompts is not None or args.read_dropped is not None
            or args.usage_history is not None or args.settings_backup is not None):
        others = snapshot_options + web_options
        if others:
            argument_parser.error(f"{others[0]} cannot be combined with {modes[0]}")
        return
    if args.web_data is None and args.vault is None:
        if web_options:
            argument_parser.error(f"{web_options[0]} needs --web-data")
        return
    if args.web_data is not None and args.vault is not None:
        argument_parser.error("--web-data and --vault cannot be combined")
    if snapshot_options:
        argument_parser.error(f"{snapshot_options[0]} cannot be combined with --web-data or --vault")
    if args.vault is not None:
        if web_options:
            argument_parser.error(f"{web_options[0]} needs --web-data")
        return
    if args.web_data == "purge":
        if web_options:
            argument_parser.error(f"{web_options[0]} cannot be combined with --web-data purge")
        return
    if args.store is None or args.applet is None:
        argument_parser.error("--web-data needs --store and --applet")
    if args.web_data == "prepare":
        if args.generation is None:
            argument_parser.error("--web-data prepare needs --generation")
        if args.keep is not None:
            argument_parser.error("--keep is only for --web-data remove")
    elif args.generation is not None:
        argument_parser.error("--generation is only for --web-data prepare")


def _provider_ids(value: str | None, argument_parser: argparse.ArgumentParser):
    if value is None:
        return None
    ids = [item.strip() for item in value.split(",") if item.strip()]
    invalid = [item for item in ids if item not in PROVIDER_IDS]
    if invalid:
        argument_parser.error(f"unsupported provider(s): {', '.join(invalid)}")
    return list(dict.fromkeys(ids))


def main(argv: Sequence[str] | None = None) -> int:
    argument_parser = parser()
    args = argument_parser.parse_args(argv)
    _check_helper_arguments(args, argument_parser)
    if args.port_owner is not None:
        payload = _port_owner_reply(args.port_owner)
    elif args.web_data == "purge":
        payload = _helper_reply(vault.purge)
    elif args.web_data is not None:
        payload = _helper_reply(lambda: webdata.run(
            args.web_data, args.store, args.applet, generation=args.generation, keep=args.keep,
        ))
    elif args.vault is not None:
        payload = _helper_reply(lambda: vault.run(args.vault, method=args.method))
    elif args.prompts is not None:
        payload = _helper_reply(lambda: promptstore.run(
            args.prompts, kind=args.kind, item=args.id, model=args.model,
        ))
    elif args.read_dropped is not None:
        payload = _dropped_reply(args.read_dropped)
    elif args.usage_history is not None:
        payload = _helper_reply(lambda: usagehistory.run(args.usage_history, sample=args.sample))
    elif args.settings_backup is not None:
        payload = _helper_reply(lambda: settingsbackup.run(args.settings_backup, data=args.data))
    elif args.catalog:
        payload = catalog_snapshot()
    elif args.detect:
        payload = detect_snapshot()
    else:
        payload = collect_snapshot(
            provider_ids=_provider_ids(args.providers, argument_parser),
        )
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0


def _helper_reply(action) -> dict[str, object]:
    """Run a helper action (--web-data, --vault, --usage-history...); any surprise becomes a bare error code.

    No traceback, path or message may reach stdout or stderr.
    """
    try:
        return action()
    except Exception:  # noqa: BLE001 - fail closed with a code only
        return {"ok": False, "error": "os-error"}


def _dropped_reply(value: str) -> dict[str, object]:
    """The file's text or a code only; any surprise fails closed as os-error."""
    try:
        return droppedfile.run(value)
    except Exception:  # noqa: BLE001 - fail closed with a code only
        return {"ok": False, "error": "os-error"}


def _port_owner_reply(port: int) -> dict[str, object]:
    """The owner word only; any surprise fails closed as unreadable."""
    try:
        return portowner.run(port)
    except Exception:  # noqa: BLE001 - fail closed with a code only
        return {"ok": False, "error": "unreadable"}


def print_json() -> int:
    """Console-script compatibility entry point."""
    return main()
