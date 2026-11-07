# Auditing an environment

Inside a single process, gilguard gets exactly one confession. It catches the first import that turns the GIL on, and after that the GIL is already on, so the next offender has nothing left to flip and walks past unnoticed. That's fine for keeping a running app honest, and no help at all when you want the whole list before you switch an app over.

The scanner gets you the whole list. It gives every installed package its own fresh interpreter, with gilguard loaded first, so no package can hide behind the one that went before it, and reports what each one did.


# Run it

``` bash
python -m gilguard
```

``` text
GIL    gilneeder                via gilneeder._speedups  [gilneeder 1.2.0]

8 checked: 7 ok, 1 re-enable the GIL, 0 failed to import.
Note: only import-time loads are checked. Extensions a package loads lazily on first use will not show up here.
```

Installing gilguard also gives you a `gilguard` command that runs the same scan.

Each `GIL` line gives the package you'd import, the extension module that flips the GIL, and the distribution and version it came from. `ERROR` lines are packages that failed to import on their own. That's often a missing optional dependency. By default it doesn't count against the result, but it also means that package wasn't checked. Pass `--strict` to treat it as a failure.

With no arguments it checks every top-level module of every installed distribution. It skips private names (starting with `_`) and packaging tools such as `pip`, `setuptools` and `wheel`.


# Check specific modules

Pass module names to check just those:

``` bash
python -m gilguard numpy pandas lxml
```

That's quicker than a full scan, and it's how you'd re-check one package after an upgrade to see if the fix took.


# Scan before you switch

You don't need a free-threaded venv to run the scan, and your project doesn't need to be on 3.14 yet. uv can stand up a throwaway free-threaded environment with your project's dependencies in it, add gilguard, and run the scanner there, leaving your real venv alone:

``` bash
uv run --isolated --python 3.14t --with gilguard python -m gilguard
```

`--isolated` gives the command its own temporary environment instead of your project's. `--python 3.14t` picks a free-threaded interpreter, downloading it if you don't have one, and uv syncs your project's dependencies into it as usual. `--with gilguard` adds the scanner on top. It's the quickest answer to "if I moved to 3.14t today, what would turn the GIL back on?", and it works from a project on 3.12 that can't install gilguard at all. Swap in `3.15t` or `3.16t` to see how the next release is shaping up.

> **Warning: When `requires-python` caps out below the target**
>
> If your project declares something like `requires-python = ">=3.11,<3.14"`, uv refuses to run it on 3.14t and says the interpreter is incompatible. Don't reach for `--no-project` to get past that. It also stops uv installing your dependencies, so the scan checks nothing, reports `0 checked`, and exits 0. Export the lockfile and pass it in instead:
>
> ``` bash
> uv export --no-hashes --no-emit-project -o /tmp/requirements.txt
> uv run --isolated --no-project --python 3.14t --with-requirements /tmp/requirements.txt --with gilguard python -m gilguard
> ```
>
> That's also the form for a project that has a `requirements.txt` and no `pyproject.toml`.

A dependency with no free-threaded wheel and a source build that fails will stop uv before the scan starts. That's a readiness answer of its own, just delivered by uv rather than gilguard.


# Options

| Option | What it does |
|----|----|
| `--json` | Print the results as JSON instead of the table. |
| `--timeout SECONDS` | Give up on a module after this long. The default is 60. A timeout shows as an error. |
| `-j N`, `--jobs N` | How many modules to check at once. It defaults to your CPU count. |
| `--strict` | Exit 1 when a module fails to import or times out, not only when one re-enables the GIL. |


# JSON output

`--json` returns one entry per module. `status` is `ok`, `gil` or `error`. A `gil` entry includes the full [report](reading-the-report.md), and an `error` entry includes the message:

``` json
{
  "gilneeder": {
    "status": "gil",
    "report": {
      "reason": "import",
      "module": "gilneeder._speedups",
      "distribution": "gilneeder",
      "version": "1.2.0",
      "chain": ["gilneeder", "gilneeder._speedups"],
      ...
    }
  },
  "ftsafe": {
    "status": "ok"
  }
}
```


# Exit codes

| Code | Meaning |
|----|----|
| `0` | No module re-enabled the GIL. Without `--strict`, some may have failed to import and gone unchecked. |
| `1` | At least one did. With `--strict`, also at least one failed to import or timed out. |
| `2` | This isn't a free-threaded interpreter, so there's nothing to scan. |

Because it exits 1 on any offender, the scan works as a CI gate without extra scripting. Use `--strict` in CI if a module that couldn't be checked should fail the build rather than pass quietly. [Tests and CI](tests-and-ci.md) has an example.


# What it can't see

The scan only imports each top-level package. Some packages are shy about their extension modules and load them later, on first use of a feature, and those won't show up. Running your test suite with gilguard active (see [Tests and CI](tests-and-ci.md)) catches those, as long as your tests exercise the code that loads them.

Every child interpreter starts without `PYTHON_GIL` or `GILGUARD_ACTION` set, even if your shell sets them, so the scan reports what each package really does.
