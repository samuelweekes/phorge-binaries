# phorge-binaries

Prebuilt [phpmicro](https://github.com/dixyes/phpmicro) runtimes for
[phorge](https://github.com/samuelweekes/phorge), built weekly from a pinned
[static-php-cli](https://github.com/crazywhalecc/static-php-cli) and published
to the fixed `runtimes` release alongside a `manifest.json` describing them.

Phorge downloads a runtime and staples an application onto it. It never
compiles PHP — which is what makes it cross platform, since a Mac can emit a
Linux binary by fetching the Linux runtime.

New releases of latest PHP versions are made weekly for all platforms via
the Github workflow.

## The Manifest

Everything a consumer needs is in `manifest.json`. This file contains all
of the available builds and their respective metadata.

```json
{
  "schema": 1,
  "php": { "8.4": "8.4.3" },
  "runtimes": {
    "8.4.3": {
      "linux-x86_64": {
        "phui": {
          "file": "php-8.4.3-micro-linux-x86_64-phui-0c9c5240.tar.gz",
          "hash": "…",
          "size": 12345678,
          "spc": "2.8.5",
          "extensions": "apcu,bcmath,…"
        }
      }
    }
  }
}
```

`php` maps a minor to the exact patch published, so a consumer pins `8.4` and
never has to name a patch. Old patches stay in `runtimes` and stay resolvable.

## The extension set

The built binaries include 55 extensions: static-php-cli's 54-extension `bulk` list,
with one removal and two additions.

**`swoole` is removed, `libxml` and `opentelemetry` are added.** swoole force-disables
JIT through its opcode handlers, and JIT is the reason these runtimes exist.
Every tier that ever exists here carries `opcache` for the same reason.
