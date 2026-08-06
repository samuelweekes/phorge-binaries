#!/usr/bin/env python3

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

SCHEMA = 1
MICRO_SFX_PATH = "buildroot/bin/micro.sfx"

PHUI_EXTENSIONS = [
    "apcu",
    "bcmath",
    "bz2",
    "calendar",
    "ctype",
    "curl",
    "dba",
    "dom",
    "event",
    "exif",
    "fileinfo",
    "filter",
    "ftp",
    "gd",
    "gmp",
    "iconv",
    "imagick",
    "imap",
    "intl",
    "libxml",
    "mbregex",
    "mbstring",
    "mysqli",
    "mysqlnd",
    "opcache",
    "openssl",
    "opentelemetry",
    "pcntl",
    "pdo",
    "pdo_mysql",
    "pdo_pgsql",
    "pdo_sqlite",
    "pgsql",
    "phar",
    "posix",
    "protobuf",
    "readline",
    "redis",
    "session",
    "shmop",
    "simplexml",
    "soap",
    "sockets",
    "sodium",
    "sqlite3",
    "sysvmsg",
    "sysvsem",
    "sysvshm",
    "tokenizer",
    "xml",
    "xmlreader",
    "xmlwriter",
    "xsl",
    "zip",
    "zlib",
]

EXTENSIONS = {
    "phui": PHUI_EXTENSIONS,
}


def progress(message: str) -> None:
    print(message, file=sys.stderr)


def get_extensions_for_tier(extension_tier: str) -> list:
    if extension_tier not in EXTENSIONS:
        raise SystemExit(
            f"unknown tier '{extension_tier}' - known tiers are {', '.join(EXTENSIONS)}"
        )

    return sorted(EXTENSIONS[extension_tier])


def get_php_version() -> str:
    result = subprocess.run(
        ["./spc", "dev:php-version"], capture_output=True, text=True
    )

    if result.returncode != 0:
        reason = result.stderr.strip() or result.stdout.strip() or "no output"
        raise SystemExit(f"`spc dev:php-version` failed: {reason}")

    return result.stdout.strip()


def get_build_filename(
    target_php: str, target_os: str, extension_tier: str, spc_version: str
) -> str:
    sha = get_build_sha(extension_tier, spc_version)

    return f"php-{target_php}-micro-{target_os}-{extension_tier}-{sha[:8]}.tar.gz"


def get_build_sha(extension_tier: str, spc_version: str) -> str:
    extensions = ",".join(get_extensions_for_tier(extension_tier))

    return hashlib.sha256(f"{spc_version}\n{extensions}".encode()).hexdigest()


def get_published_manifest(manifest_path: str) -> dict:
    try:
        with open(manifest_path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        raise SystemExit(f"{manifest_path} exists but did not contain valid json: {e}")


def get_build_artifacts(manifest_path: str) -> list[dict]:
    return [
        artifact
        for targets in get_published_manifest(manifest_path)
        .get("runtimes", {})
        .values()
        for tiers in targets.values()
        for artifact in tiers.values()
    ]


def is_previously_built(manifest_path: str, build_identifier: str) -> bool:
    return any(
        artifact.get("file") == build_identifier
        for artifact in get_build_artifacts(manifest_path)
    )


def package_build_with_metadata(
    php_version: str, os_target: str, extension_tier: str, spc_version: str
) -> None:
    micro_sfx_path = Path(MICRO_SFX_PATH)
    if not micro_sfx_path.is_file():
        raise SystemExit(f"No {MICRO_SFX_PATH} found - run spc build first")

    Path("out").mkdir(parents=True, exist_ok=True)
    filename = get_build_filename(php_version, os_target, extension_tier, spc_version)

    subprocess.run(
        [
            "tar",
            "--create",
            "--gzip",
            "--file",
            f"out/{filename}",
            "--directory",
            str(micro_sfx_path.parent),
            micro_sfx_path.name,
        ],
        check=True,
    )

    tarball = Path(f"out/{filename}")

    metadata = {
        "file": filename,
        "hash": hashlib.sha256(tarball.read_bytes()).hexdigest(),
        "size": tarball.stat().st_size,
        "php_version": php_version,
        "spc_version": spc_version,
        "os_target": os_target,
        "extension_tier": extension_tier,
        "extensions": ",".join(get_extensions_for_tier(extension_tier)),
    }

    with open(f"out/{filename}.metadata.json", "w") as f:
        json.dump(metadata, f, indent=4)


def record_published_build(
    manifest_path: str,
    php_version: str,
    os_target: str,
    extension_tier: str,
    spc_version: str,
) -> None:
    filename = get_build_filename(php_version, os_target, extension_tier, spc_version)
    artifact = next(
        (a for a in get_build_artifacts(manifest_path) if a.get("file") == filename),
        None,
    )

    if artifact is None:
        raise SystemExit(f"{manifest_path} does not describe {filename}")

    Path("out").mkdir(parents=True, exist_ok=True)

    metadata = {
        "file": filename,
        "hash": artifact["hash"],
        "size": artifact["size"],
        "php_version": php_version,
        "spc_version": spc_version,
        "os_target": os_target,
        "extension_tier": extension_tier,
        "extensions": artifact["extensions"],
    }

    with open(f"out/{filename}.metadata.json", "w") as f:
        json.dump(metadata, f, indent=4)


def enforce_write_once(records_path: Path, manifest_path: str) -> None:
    published = {
        artifact["file"]: artifact for artifact in get_build_artifacts(manifest_path)
    }

    # NOTE: SPC builds may not be byte-identical week to week, which means that we can have the
    # exact same build conditions but clobber the release artifact. To combat this,
    # we check if we've already published a file with these build conditions and (if so) we
    # delete the new build and set the metadata to the old build's hash. The user gets the same
    # file as before.
    for record in sorted(records_path.glob("*.metadata.json")):
        metadata = json.loads(record.read_text())
        prior = published.get(metadata["file"])

        if prior is None:
            continue

        metadata["hash"] = prior["hash"]
        metadata["size"] = prior["size"]
        record.write_text(json.dumps(metadata, indent=4))

        (records_path / metadata["file"]).unlink(missing_ok=True)

        progress(
            f"write-once: {metadata['file']} was rebuilt but is already "
            f"published - keeping the published bytes ({prior['hash'][:12]}...)"
        )


def version_sort_key(php_version: str) -> tuple:
    return tuple(int(part) if part.isdigit() else 0 for part in php_version.split("."))


def generate_output_manifest(records_dir: str, manifest_path: str) -> None:
    records_path = Path(records_dir)

    if not records_path.is_dir():
        raise SystemExit(f"No {records_dir} found")

    enforce_write_once(records_path, manifest_path)

    records = sorted(records_path.glob("*.metadata.json"))

    if not records:
        raise SystemExit(f"No records found in {records_dir} - nothing to publish")

    # NOTE: We start from everything already published rather than from this run's matrix.
    # A tarball stays on the release forever, so its entry has to stay in the manifest
    # forever too - a project pinned to a patch we no longer build still needs to look up
    # the hash of the file it locked. This run's records are overlaid on top.
    runtimes = get_published_manifest(manifest_path).get("runtimes", {})

    for file_path in records:
        metadata = json.loads(file_path.read_text())

        runtimes.setdefault(metadata["php_version"], {}).setdefault(
            metadata["os_target"], {}
        )[metadata["extension_tier"]] = {
            "file": metadata["file"],
            "hash": metadata["hash"],
            "size": metadata["size"],
            "spc": metadata["spc_version"],
            "extensions": metadata["extensions"],
        }

    php = {}

    # NOTE: A consumer's phorge lockfile pins a minor version and we resolve it
    # to the patch they get, so they never have to name one explicitly. Old patches
    # stay in the manifest and stay resolvable. We keep a lookup to the latest PHP patch
    # only so that when Phorge requests a minor version, it gets the latest patch.
    for php_version in runtimes:
        php_version_minor = ".".join(php_version.split(".")[:2])
        current = php.get(php_version_minor, "0")

        if version_sort_key(php_version) >= version_sort_key(current):
            php[php_version_minor] = php_version

    by_version = lambda item: version_sort_key(item[0])

    print(
        json.dumps(
            {
                "schema": SCHEMA,
                "php": dict(sorted(php.items(), key=by_version)),
                "runtimes": dict(sorted(runtimes.items(), key=by_version)),
            },
            indent=4,
        )
    )


def handle_get_extensions_for_tier(args) -> None:
    print(",".join(get_extensions_for_tier(args.extension_tier)))


def handle_get_build_filename(args) -> None:
    print(
        get_build_filename(
            get_php_version(),
            args.os_target,
            args.extension_tier,
            args.spc_version,
        )
    )


def handle_is_previously_built(args) -> None:
    print(
        "true"
        if is_previously_built(args.manifest_path, args.build_identifier)
        else "false"
    )


def handle_package_build_with_metadata(args) -> None:
    package_build_with_metadata(
        get_php_version(),
        args.os_target,
        args.extension_tier,
        args.spc_version,
    )


def handle_record_published_build(args) -> None:
    record_published_build(
        args.manifest_path,
        get_php_version(),
        args.os_target,
        args.extension_tier,
        args.spc_version,
    )


def handle_generate_output_manifest(args) -> None:
    generate_output_manifest(args.records_dir, args.manifest_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tools.py")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "get-extensions-for-tier",
        help="print a tier's extension set, comma separated, for spc to build against",
    )
    p.add_argument("extension_tier")
    p.set_defaults(func=handle_get_extensions_for_tier)

    p = sub.add_parser(
        "get-build-identifier",
        help="print the filename this build would produce; run after `spc extract "
        "php-src`, which is what resolves the php patch version",
    )
    p.add_argument("os_target")
    p.add_argument("extension_tier")
    p.add_argument("spc_version")
    p.set_defaults(func=handle_get_build_filename)

    p = sub.add_parser(
        "is-previously-built",
        help="print true when the manifest already describes this file, so the build "
        "can be skipped, and false when it does not",
    )
    p.add_argument("manifest_path")
    p.add_argument("build_identifier")
    p.set_defaults(func=handle_is_previously_built)

    p = sub.add_parser(
        "package-build",
        help="package the runtime spc just built into out/, alongside the record the "
        "publish job reads to describe it",
    )
    p.add_argument("os_target")
    p.add_argument("extension_tier")
    p.add_argument("spc_version")
    p.set_defaults(func=handle_package_build_with_metadata)

    p = sub.add_parser(
        "record-published-build",
        help="record the published artifact for a build that was skipped, so the cell "
        "still reports in; run instead of package-build",
    )
    p.add_argument("manifest_path")
    p.add_argument("os_target")
    p.add_argument("extension_tier")
    p.add_argument("spc_version")
    p.set_defaults(func=handle_record_published_build)

    p = sub.add_parser(
        "generate-output-manifest",
        help="merge this run's records into the manifest phorge consumes and print it; "
        "artifacts already published keep the bytes they were published with",
    )
    p.add_argument("records_dir")
    p.add_argument("manifest_path")
    p.set_defaults(func=handle_generate_output_manifest)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
