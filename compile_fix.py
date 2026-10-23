#!/usr/bin/env python3
"""

python3 compile_fix.py \
  --compile-commands /path/to/compile_commands.json \
  --source-root /path/to/src \
  --file yourfile.cpp \
  --output-dir /tmp/o \
  --diagnose
  

compile_fix.py - compile ONE .cpp file, capture errors, ask a local Ollama model
for a fix, verify the fix compiles, open a diff in VS Code and (on approval)
update the file.

Flow
  1. Look the file up in compile_commands.json and compile it (object output is
     thrown away: -o /dev/null).  Your '#pragma GCC diagnostic error ...' lines
     are part of the file, so they are honoured naturally.
  2. If it compiles cleanly -> done.
  3. Otherwise send the file + diagnostics to Ollama.  The model replies with
     SEARCH/REPLACE blocks (far more reliable than asking a small model for a
     unified diff).  They are applied in memory to a working copy.
  3b. GUARDRAILS: the change is checked for "cosmetic" fixes before it is even
     compiled (see check_guardrails).  A rejected change is discarded and the
     reason is sent back to the model.
  4. The working copy is compiled again (via a temp file next to the original so
     relative #includes still work).  If errors remain, the loop repeats with the
     new errors (--max-attempts).
  5. A unified diff + a '<stem>.proposed<ext>' file are written to --output-dir
     and `code --diff original proposed` is opened.  Behaviour-change REVIEW
     flags (see review_flags) are printed and saved to '<stem>.flags.txt'.
  6. You answer y/N in the terminal.  On 'y' the original is backed up
     (<name>.orig in --output-dir) and overwritten.

Guardrails (hard rejects, per round)
  * suppression added : '#pragma GCC diagnostic', NOLINT, NOSONAR, coverity[...]
                        comments, (void)x; casts, static_cast<void>, -fpermissive,
                        -Wno-..., [[maybe_unused]], __attribute__((unused)), '#if 0'
  * checks removed    : fewer assert()/static_assert()/#error than before
  * code deleted      : more than --max-deleted-lines substantive lines removed
                        that do not reappear in the new text
  * too big           : more than --max-change-lines lines changed in one round
Review flags (soft, never block, but disable --auto-apply)
  * control flow / return / loop / switch lines added, removed or altered
  * comparison / logical operators or numeric literals changed
  * a variable/function name dropped from a statement (the classic way to
    "fix" an uninitialized-variable error without fixing it)
Use --no-guardrails to switch the hard rejects off.

Only the Python standard library is used.
"""
import argparse
import collections
import difflib
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

SYSTEM_PROMPT = """You are a C++ compiler-error fixing assistant.
You receive one source file (each line is prefixed with its line number and '| ';
the prefix is NOT part of the code) and the g++ diagnostics for it.

Rules:
- Fix the ROOT CAUSE with the smallest possible change.
- NEVER remove, edit or add '#pragma GCC diagnostic' lines. They are intentional
  and turn warnings into errors. Fix the code instead of silencing the diagnostic.
- Do NOT silence a diagnostic: no '(void)x;' casts, no static_cast<void>, no
  NOLINT/NOSONAR comments, no [[maybe_unused]], no '#if 0', no -fpermissive.
- Do NOT delete assert()/static_assert()/#error, error-handling branches or whole
  statements just to make the error go away.
- Do not reformat, rename, or touch unrelated code. Do not change function
  signatures unless the error requires it. Keep the change to a few lines.
- Reply ONLY with one or more SEARCH/REPLACE blocks in exactly this format:

<<<<<<< SEARCH
(existing lines, copied exactly, WITHOUT the line-number prefix)
=======
(replacement lines)
>>>>>>> REPLACE

- Each SEARCH text must match the file exactly and be unique in the file; include
  a few neighbouring lines if needed.
- After the blocks add ONE short line starting with 'NOTE:' describing the fix.
"""

BLOCK_RE = re.compile(
    r"<<<<<<< SEARCH\r?\n(.*?)\r?\n=======\r?\n(.*?)>>>>>>> REPLACE", re.DOTALL)
DIAG_RE = re.compile(r"^(?P<file>[^\s:][^:]*):(?P<line>\d+):(?:\d+:)?\s*"
                     r"(?P<sev>fatal error|error|warning)", re.MULTILINE)
STRIP_WITH_ARG = {"-o", "-MF", "-MT", "-MQ"}
STRIP_FLAGS = {"-MD", "-MMD", "-MP", "-M", "-MM", "-MG"}


def log(msg, verbose_only=False, verbose=True):
    if verbose_only and not verbose:
        return
    print(msg, flush=True)


# --------------------------------------------------------------------------- IO
def read_text(path):
    raw = open(path, "rb").read()
    text = raw.decode("utf-8", errors="surrogateescape")
    crlf = "\r\n" in text
    return text.replace("\r\n", "\n"), crlf, hashlib.sha256(raw).hexdigest()


def write_text(path, text, crlf):
    if crlf:
        text = text.replace("\n", "\r\n")
    with open(path, "wb") as f:
        f.write(text.encode("utf-8", errors="surrogateescape"))


# ------------------------------------------------------------ compile_commands
def find_entry(cc_path, target):
    entries = json.load(open(cc_path, encoding="utf-8"))
    t = os.path.normpath(target)
    hits = []
    for e in entries:
        full = os.path.normpath(os.path.join(e.get("directory", ""), e["file"]))
        if full == t or full.endswith(os.sep + t) or os.path.basename(full) == t:
            e["_full"] = full
            hits.append(e)
    if not hits:
        sys.exit(f"ERROR: '{target}' not found in {cc_path}")
    if len(hits) > 1:
        names = "\n  ".join(h["_full"] for h in hits)
        sys.exit(f"ERROR: '{target}' is ambiguous, matches:\n  {names}\n"
                 "Give a longer path.")
    return hits[0]


def build_cmd(entry, extra_flags, source_override=None):
    args = list(entry["arguments"]) if "arguments" in entry \
        else shlex.split(entry["command"])
    directory = entry.get("directory", ".")
    out, skip, replaced = [], False, False
    full_real = os.path.realpath(entry["_full"])
    for a in args:
        if skip:
            skip = False
            continue
        if a in STRIP_WITH_ARG:
            skip = True
            continue
        if a in STRIP_FLAGS:
            continue
        if (source_override and not a.startswith("-")
                and (os.path.normpath(os.path.join(directory, a)) == entry["_full"]
                     or os.path.realpath(os.path.join(directory, a)) == full_real)):
            a = source_override
            replaced = True
        out.append(a)
    if source_override and not replaced:
        sys.exit("ERROR: could not find the source file in the compile command, so the "
                 "pragma-injected copy would NOT be compiled (warnings would pass silently).\n"
                 "  entry file: %s\n  command   : %s" % (entry["file"], " ".join(args)))
    if "-c" not in out:
        out.append("-c")
    out += ["-o", "/dev/null", "-fdiagnostics-color=never"]
    out += shlex.split(extra_flags or "")
    return out, directory


LAST_CMD = None


def run_compile(entry, extra_flags, source_override=None, timeout=300):
    cmd, cwd = build_cmd(entry, extra_flags, source_override)
    global LAST_CMD
    LAST_CMD = (cmd, cwd)
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       errors="replace", timeout=timeout)
    return p.returncode, (p.stderr + p.stdout).strip(), cmd


def compile_text(entry, text, crlf, extra_flags):
    """Compile in-memory text via a temp file beside the original."""
    src = entry["_full"]
    d, base = os.path.split(src)
    stem, ext = os.path.splitext(base)
    tmp = os.path.join(d, f".{stem}.__cfix__{ext}")
    try:
        write_text(tmp, text, crlf)
        rc, out, _ = run_compile(entry, extra_flags, source_override=tmp)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return rc, out.replace(os.path.basename(tmp), base)


# ------------------------------------------------------------------- prompting
def errors_for_file(diag_text, basename):
    """Line numbers of diagnostics that belong to the target file."""
    lines = []
    for m in DIAG_RE.finditer(diag_text):
        if os.path.basename(m.group("file")) == basename and m.group("sev") != "warning":
            lines.append(int(m.group("line")))
    return sorted(set(lines))


def numbered_view(text, err_lines, full_limit=400, ctx=40):
    lines = text.split("\n")
    if len(lines) <= full_limit or not err_lines:
        return "\n".join(f"{i:5d}| {l}" for i, l in enumerate(lines, 1))
    keep = set()
    for n in err_lines:
        keep.update(range(max(1, n - ctx), min(len(lines), n + ctx) + 1))
    out, prev = [], 0
    for i in sorted(keep):
        if prev and i != prev + 1:
            out.append("      | ... (lines omitted) ...")
        out.append(f"{i:5d}| {lines[i - 1]}")
        prev = i
    return "\n".join(out)


def error_count(diag_text):
    return sum(1 for m in DIAG_RE.finditer(diag_text) if m.group("sev") != "warning")


def first_error_block(diag_text, basename):
    """Text of the first error located in the target file (small models do better
    when given one problem at a time)."""
    ms = list(DIAG_RE.finditer(diag_text))
    for i, m in enumerate(ms):
        if m.group("sev") != "warning" and os.path.basename(m.group("file")) == basename:
            end = ms[i + 1].start() if i + 1 < len(ms) else len(diag_text)
            return diag_text[m.start():end].strip()
    return diag_text


def build_prompt(text, diag, basename, note=""):
    err_lines = errors_for_file(diag, basename)
    diag = diag if len(diag) <= 8000 else diag[:8000] + "\n... (truncated)"
    p = (f"File: {basename}\n\n=== SOURCE ===\n{numbered_view(text, err_lines)}\n\n"
         f"=== COMPILER OUTPUT ===\n{diag}\n")
    if note:
        p += f"\n=== PROBLEM WITH YOUR PREVIOUS REPLY ===\n{note}\n"
    return p + "\nReturn the SEARCH/REPLACE blocks now."


def call_ollama(url, model, system, user, num_ctx, timeout):
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "stream": False,
        "think": False,
        "options": {"temperature": 0.1, "num_ctx": num_ctx},
    }
    req = urllib.request.Request(url.rstrip("/") + "/api/chat",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
    except (urllib.error.URLError, TimeoutError) as e:
        sys.exit(f"ERROR: cannot reach Ollama at {url}: {e}")
    txt = data.get("message", {}).get("content", "")
    return re.sub(r"<think>.*?</think>", "", txt, flags=re.DOTALL).strip()


# ----------------------------------------------------------- applying the reply
def strip_prefixes(block):
    ls = block.split("\n")
    if ls and all(re.match(r"^\s*\d+\| ?", l) for l in ls if l.strip()):
        return "\n".join(re.sub(r"^\s*\d+\| ?", "", l) for l in ls)
    return block


def locate(content, search):
    n = content.count(search)
    if n == 1:
        return content.find(search), len(search)
    if n > 1:
        raise ValueError("SEARCH text matches more than one place; add more context lines")
    cl, sl = content.split("\n"), search.split("\n")
    hits = [i for i in range(len(cl) - len(sl) + 1)
            if all(cl[i + j].strip() == sl[j].strip() for j in range(len(sl)))]
    if len(hits) != 1:
        raise ValueError("SEARCH text not found in the file (must match exactly)")
    start = sum(len(l) + 1 for l in cl[:hits[0]])
    length = sum(len(l) + 1 for l in cl[hits[0]:hits[0] + len(sl)]) - 1
    return start, length


def pragma_count(text):
    return sum(1 for l in text.split("\n") if "#pragma GCC diagnostic" in l)


def apply_reply(content, reply):
    blocks = BLOCK_RE.findall(reply)
    if not blocks:
        raise ValueError("no SEARCH/REPLACE blocks found in the reply")
    new = content
    for i, (s, r) in enumerate(blocks, 1):
        s, r = strip_prefixes(s), strip_prefixes(r)
        if r.endswith("\n"):
            r = r[:-1]
        if not s.strip():
            raise ValueError(f"block {i}: empty SEARCH text")
        try:
            start, length = locate(new, s)
        except ValueError as e:
            raise ValueError(f"block {i}: {e}")
        new = new[:start] + r + new[start + length:]
    if pragma_count(new) < pragma_count(content):
        raise ValueError("you removed a '#pragma GCC diagnostic' line; "
                         "those must stay untouched")
    return new


# ------------------------------------------------------------------ guardrails
# Lines that silence a diagnostic instead of fixing it.
SUPPRESS_RE = re.compile(
    r"#\s*pragma\s+(GCC\s+diagnostic|GCC\s+system_header|warning|clang\s+diagnostic)"
    r"|NOLINT|NOSONAR|coverity\s*\["
    r"|-fpermissive|-Wno-"
    r"|^\s*\(\s*void\s*\)\s*[A-Za-z_(*&]"
    r"|static_cast\s*<\s*void\s*>"
    r"|\[\[\s*maybe_unused\s*\]\]"
    r"|__attribute__\s*\(\(\s*(unused|used)"
    r"|^\s*#\s*if\s+0\b")
# Checks that must not disappear.
ASSERT_RE = re.compile(
    r"\b(static_assert|assert|Q_ASSERT\w*|configASSERT|ASSERT)\s*\(|^\s*#\s*error\b")
# Behaviour-relevant keywords (control flow, loops, returns).
KEYWORD_RE = re.compile(
    r"\b(if|else|while|for|do|switch|case|default|return|goto|break|continue|throw|catch)\b")
OPERATOR_RE = re.compile(r"==|!=|<=|>=|&&|\|\||(?<![<>-])<(?![<=])|(?<![<>-])>(?![>=])|!(?!=)")
IDENT_RE = re.compile(r"[A-Za-z_]\w*")
NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?(?:[uUlLfF]*)\b|\b0[xX][0-9a-fA-F]+\b")


def _code_lines(text):
    return text.split("\n")


def _strip_line_comment(line):
    return re.sub(r"//.*$", "", line)


def _substantive(line):
    s = line.strip()
    if not s or s in ("{", "}", "};", "{}", ");"):
        return False
    return not (s.startswith("//") or s.startswith("/*") or s.startswith("*"))


def _diff_ops(old_text, new_text):
    old, new = _code_lines(old_text), _code_lines(new_text)
    sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
    return old, new, [op for op in sm.get_opcodes() if op[0] != "equal"]


def check_guardrails(old_text, new_text, max_change=12, max_deleted=2):
    """Hard checks on one proposed change.  Returns a list of violation strings
    (empty = acceptable)."""
    old, new, ops = _diff_ops(old_text, new_text)
    out = []

    changed = sum(max(i2 - i1, j2 - j1) for _, i1, i2, j1, j2 in ops)
    if max_change and changed > max_change:
        out.append(f"the change touches {changed} lines (limit {max_change}); "
                   "fix only the reported error with a smaller edit")

    old_set = {l.strip() for l in old}
    added, removed = [], []
    for _, i1, i2, j1, j2 in ops:
        removed += [l for l in old[i1:i2]]
        added += [(j + 1, l) for j, l in zip(range(j1, j2), new[j1:j2])]

    for n, l in added:
        if l.strip() in old_set:
            continue                      # an existing line that merely moved
        if SUPPRESS_RE.search(l):
            out.append(f"line {n} silences a diagnostic instead of fixing it: "
                       f"'{l.strip()[:80]}'")

    def n_asserts(lines):
        return sum(1 for l in lines if ASSERT_RE.search(_strip_line_comment(l)))
    if n_asserts(new) < n_asserts(old):
        out.append("an assert()/static_assert()/#error was removed; keep all checks")

    added_set = collections.Counter(l.strip() for _, l in added)
    gone = []
    for l in removed:
        s = l.strip()
        if not _substantive(l):
            continue
        if added_set[s] > 0:
            added_set[s] -= 1             # moved, not deleted
            continue
        gone.append(s)
    # a removed line that was replaced by a changed line is an edit, not a deletion
    n_added_subst = sum(1 for _, l in added if _substantive(l))
    deleted = max(0, len(gone) - n_added_subst)
    if max_deleted is not None and deleted > max_deleted:
        out.append(f"{deleted} statements were deleted without replacement "
                   f"(limit {max_deleted}); do not delete code to hide an error")
    return out


def review_flags(old_text, new_text):
    """Soft flags: places where the fix may have changed behaviour.
    Returns a list of 'line N: reason: code' strings (new-file line numbers)."""
    old, new, ops = _diff_ops(old_text, new_text)
    flags, seen = [], set()

    def add(n, why, code):
        key = (n, why)
        if key not in seen:
            seen.add(key)
            flags.append(f"line {n}: {why}: {code.strip()[:90]}")

    for tag, i1, i2, j1, j2 in ops:
        o, nw = old[i1:i2], new[j1:j2]
        pairs = min(len(o), len(nw)) if tag == "replace" else 0
        for k in range(pairs):
            ol, nl, n = _strip_line_comment(o[k]), _strip_line_comment(nw[k]), j1 + k + 1
            if not (_substantive(ol) or _substantive(nl)):
                continue
            if KEYWORD_RE.findall(ol) != KEYWORD_RE.findall(nl):
                add(n, "control flow / return changed", nw[k])
            if OPERATOR_RE.findall(ol) != OPERATOR_RE.findall(nl):
                add(n, "comparison/logical operator changed", nw[k])
            if NUMBER_RE.findall(ol) != NUMBER_RE.findall(nl):
                add(n, "numeric literal added or changed", nw[k])
            # a name that vanished from the line (typo/rename fixes are ignored)
            new_ids = set(IDENT_RE.findall(nl))
            for name in sorted(set(IDENT_RE.findall(ol)) - new_ids):
                if name in ("static", "const", "auto", "unsigned", "signed") or \
                   any(difflib.SequenceMatcher(None, name, m).ratio() >= 0.8
                       for m in new_ids - set(IDENT_RE.findall(ol))):
                    continue
                add(n, f"'{name}' dropped from the statement (value no longer used?)", nw[k])
        for l in o[pairs:]:
            if _substantive(l) and KEYWORD_RE.search(_strip_line_comment(l)):
                add(i1 + 1, "control-flow/return line REMOVED", l)
        for k, l in enumerate(nw[pairs:], pairs):
            if _substantive(l) and KEYWORD_RE.search(_strip_line_comment(l)):
                add(j1 + k + 1, "control-flow/return line ADDED", l)
    return flags



# ------------------------------------------------------------- auto pragmas
AUTO_MARK = "// [cfix-auto]"
KEEP_ON_CMDLINE = {"-Wall", "-Wextra", "-Werror", "-Wpedantic"}


def split_flags(extra):
    """-> (flags that stay on the command line, [-Wxxx flags to become pragmas])"""
    keep, wflags = [], []
    for f in shlex.split(extra or ""):
        m = re.match(r"^-W([A-Za-z][\w+-]*)$", f)
        if (m and f not in KEEP_ON_CMDLINE
                and not m.group(1).startswith(("error", "no-"))):
            wflags.append(f)
        else:
            keep.append(f)
    return " ".join(shlex.quote(k) for k in keep), wflags


def inject_pragmas(text, wflags):
    """Insert '#pragma GCC diagnostic error "-Wxxx"' after the LAST #include, so
    only this file's own code is affected, never the headers."""
    lines = text.split("\n")
    last = -1
    for i, l in enumerate(lines):
        if re.match(r"\s*#\s*include\b", l):
            last = i
    block = ['#pragma GCC diagnostic error "%s" %s' % (f, AUTO_MARK) for f in wflags]
    lines[last + 1:last + 1] = block
    return "\n".join(lines)


def strip_auto(text):
    return "\n".join(l for l in text.split("\n") if AUTO_MARK not in l)


def collect_folder_entries(cc_path, source_root, folder):
    entries = json.load(open(cc_path, encoding="utf-8"))
    root = os.path.abspath(os.path.join(source_root, folder))
    out = []
    for e in entries:
        full = os.path.abspath(os.path.join(e.get("directory", ""), e["file"]))
        if (full.startswith(root + os.sep)
                and full.lower().endswith((".cpp", ".cc", ".cxx"))):
            e["_full"] = full
            out.append(e)
    return sorted(out, key=lambda e: e["_full"])



# ------------------------------------------------------------------ diagnose
CANARY = """
static void cfix_canary_fn()
{
    int cfixA;
    {
        int cfixA;
    }
}
"""


def diagnose(a):
    entry = find_entry(a.compile_commands, a.file)
    src = entry["_full"]
    base = os.path.basename(src)
    args = list(entry["arguments"]) if "arguments" in entry else shlex.split(entry["command"])
    print("== compile_commands entry ==")
    print("directory :", entry.get("directory"))
    print("file      :", entry["file"], "->", src)
    if not os.path.isfile(src):
        print("PROBLEM: that file does not exist on disk.")
        return 2
    st = os.stat(src)
    import time
    print("on disk   : %d bytes, modified %s  (save your editor buffer if this is old)"
          % (st.st_size, time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))))
    print("command   :", " ".join(shlex.quote(x) for x in args))
    try:
        v = subprocess.run([args[0], "--version"], capture_output=True, text=True).stdout.splitlines()
        print("compiler  :", v[0] if v else args[0])
    except OSError as e:
        print("PROBLEM: cannot run compiler '%s': %s" % (args[0], e))
    probs = []
    for i, t in enumerate(args):
        if t == "-w":
            probs.append("'-w' suppresses ALL warnings")
        elif t.startswith("-Wno-"):
            probs.append("'%s' disables a warning (the pragma should override it, "
                         "but check)" % t)
        elif t.startswith("-system-header-prefix") or t == "-Wsystem-headers":
            pass
    if os.path.basename(args[0]) not in ("g++", "gcc", "c++", "cc") and "g++" not in args[0]:
        probs.append("compiler is '%s' (wrapper or non-gcc?)" % args[0])
    print("\n== suspicious flags ==")
    print("\n".join("  - " + x for x in probs) if probs else "  none found")

    flags = "-O1 -Wshadow -Wunused-variable -Wuninitialized"
    print("\n== A: your file, compiled with %s ==" % flags)
    rc, out, _ = run_compile(entry, flags)
    mine = [l for l in out.splitlines() if base in l and "warning" in l]
    print("exit code %d, %d warning line(s) in %s" % (rc, len(mine), base))
    for l in mine[:8]:
        print("  " + l[:160])

    print("\n== B: canary (unused + shadowed variable appended to a copy) ==")
    text, crlf, _ = read_text(src)
    rc, out = compile_text(entry, text.rstrip("\n") + "\n" + CANARY, crlf, flags)
    hit = [l for l in out.splitlines() if "cfixA" in l]
    for l in hit[:4]:
        print("  " + l[:160])
    print("canary warnings:", len(hit))

    print("\n== verdict ==")
    if hit and not mine:
        print("The compile command DOES report warnings, but none for this file's own "
              "code. Your snippet is likely not compiled: unsaved edit, inside #if 0 / "
              "a disabled #ifdef, in an uninstantiated template, or this is not the "
              "file you edited.")
    elif hit and mine:
        print("Warnings work and your file produces some. Run the normal task with "
              "--auto-pragmas; if it still says 'Compiles cleanly', send me its output.")
    else:
        print("The canary did NOT warn: the compile command itself suppresses warnings "
              "(see suspicious flags above, or a wrapper/ccache script).")
    return 0


# ------------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--compile-commands", required=True)
    ap.add_argument("--source-root", required=True)
    ap.add_argument("--file", default=None,
                    help="file as in compile_commands.json (basename or path suffix)")
    ap.add_argument("--folder", default=None,
                    help="folder (relative to --source-root); every .cpp/.cc/.cxx "
                         "under it, sub-folders included, is processed one by one")
    ap.add_argument("--diagnose", action="store_true",
                    help="with --file: explain why warnings are (not) reported, then exit")
    ap.add_argument("--auto-pragmas", action="store_true",
                    help="turn -Wxxx flags in --extra-flags into '#pragma GCC "
                         "diagnostic error' lines after the last #include (in the "
                         "working copy only; they are stripped from the proposed file)")
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--ollama-url", default=os.environ.get("OLLAMA_URL", "http://localhost:11434"))
    ap.add_argument("--chat-model", default="qwen3:8b")
    ap.add_argument("--num-ctx", type=int, default=16384)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--max-attempts", type=int, default=20,
                    help="maximum fix rounds (loop runs until the file compiles clean)")
    ap.add_argument("--max-stalls", type=int, default=3,
                    help="stop after this many rounds in a row without fewer errors")
    ap.add_argument("--first-error-only", action="store_true",
                    help="show the model only the first error each round")
    ap.add_argument("--extra-flags", default="",
                    help="extra compiler flags, e.g. '-O1' (use --extra-flags=-O1)")
    ap.add_argument("--no-guardrails", action="store_true",
                    help="disable the hard cosmetic-fix rejects")
    ap.add_argument("--max-change-lines", type=int, default=12,
                    help="guardrail: max lines changed in ONE round (0 = no limit)")
    ap.add_argument("--max-deleted-lines", type=int, default=2,
                    help="guardrail: max statements deleted without replacement per round")
    ap.add_argument("--vscode", action="store_true", help="open the diff in VS Code")
    ap.add_argument("--auto-apply", action="store_true",
                    help="apply without asking (only if the fix compiles and has no review flags)")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()

    if a.diagnose:
        if not a.file:
            ap.error("--diagnose needs --file")
        return diagnose(a)
    if bool(a.file) == bool(a.folder):
        ap.error("give exactly one of --file or --folder")
    if a.folder:
        entries = collect_folder_entries(a.compile_commands, a.source_root, a.folder)
        if not entries:
            sys.exit("ERROR: no .cpp files from compile_commands.json under '%s'" % a.folder)
        log("Folder mode: %d file(s)" % len(entries))
        results = {}
        for n, e in enumerate(entries, 1):
            log("\n" + "=" * 70 + "\n(%d/%d) %s\n" % (n, len(entries), e["_full"]) + "=" * 70)
            results[e["_full"]] = process_entry(a, e)
        log("\nSummary (0=ok/applied/skipped, 1=no fix, 2=errors not in file):")
        for f, rc in results.items():
            log("  %d  %s" % (rc, f))
        return 1 if any(v == 1 for v in results.values()) else 0
    return process_entry(a, find_entry(a.compile_commands, a.file))


def process_entry(a, entry):
    src = entry["_full"]
    base = os.path.basename(src)
    stem, ext = os.path.splitext(base)
    if a.folder:   # avoid name clashes between same-named files in different folders
        stem = os.path.splitext(os.path.relpath(src, os.path.abspath(a.source_root)))[0].replace(os.sep, "__")
    os.makedirs(a.output_dir, exist_ok=True)

    original, crlf, orig_hash = read_text(src)
    if a.auto_pragmas:
        cflags, wflags = split_flags(a.extra_flags)
        base_text = inject_pragmas(original, wflags) if wflags else original
        log("      auto-pragmas: %s" % (", ".join(wflags) or "(no -W flags to convert)"))
    else:
        cflags, base_text = a.extra_flags, original

    log(f"[1/4] Compiling {src}")
    if a.auto_pragmas:
        rc, diag = compile_text(entry, base_text, crlf, cflags)
        if LAST_CMD:
            log("      cwd : %s\n      cmd : %s" % (LAST_CMD[1], " ".join(shlex.quote(c) for c in LAST_CMD[0])))
    else:
        rc, diag, cmd = run_compile(entry, cflags)
        log("      " + " ".join(shlex.quote(c) for c in cmd), True, a.verbose)
    if rc == 0:
        log("      Compiles cleanly - nothing to fix.")
        if diag:
            log(diag)
        return 0
    log("      Compilation FAILED:\n" + diag + "\n")
    if not errors_for_file(diag, base):
        log("      None of the errors are in this file (headers / link / config?). "
            "Not asking the model to guess; fix those manually.")
        return 2

    working, note, still_failing = base_text, "", True
    cur_count = max(1, error_count(diag))
    stalls = 0
    for rnd in range(1, a.max_attempts + 1):
        log(f"[2/4] Round {rnd}/{a.max_attempts}: {cur_count} error(s) left, "
            f"asking {a.chat_model}")
        shown = first_error_block(diag, base) if a.first_error_only else diag
        reply = call_ollama(a.ollama_url, a.chat_model, SYSTEM_PROMPT,
                            build_prompt(working, shown, base, note),
                            a.num_ctx, a.timeout)
        log(reply, True, a.verbose)
        try:
            candidate = apply_reply(working, reply)
        except ValueError as e:
            note = str(e)
            stalls += 1
            log(f"      Could not apply reply: {note}")
        else:
            violations = [] if (a.no_guardrails or candidate == working) else \
                check_guardrails(working, candidate, a.max_change_lines, a.max_deleted_lines)
            if candidate == working:
                note = "your edit changed nothing"
                stalls += 1
                log("      Reply changed nothing.")
            elif violations:
                note = ("your change was REJECTED by the guardrails and DISCARDED:\n- "
                        + "\n- ".join(violations)
                        + "\nFix the root cause of the compiler error instead.")
                stalls += 1
                log("      Rejected by guardrails:\n        " + "\n        ".join(violations))
            else:
                log("[3/4] Verifying the change")
                rc, new_diag = compile_text(entry, candidate, crlf, cflags)
                if rc == 0:
                    working, still_failing = candidate, False
                    log(f"      Compiles cleanly after round {rnd}.")
                    break
                new_count = max(1, error_count(new_diag))
                if new_count > cur_count:
                    # worse than before: discard this round, keep the previous working copy
                    stalls += 1
                    note = (f"your last change raised the error count from {cur_count} "
                            f"to {new_count} and was DISCARDED. Errors it caused:\n"
                            + new_diag[:1500])
                    log(f"      Discarded: errors went {cur_count} -> {new_count}.")
                else:
                    stalls = 0 if new_count < cur_count else stalls + 1
                    log(f"      Kept: errors {cur_count} -> {new_count}.")
                    working, diag, cur_count, note = candidate, new_diag, new_count, ""
        if stalls >= a.max_stalls:
            log(f"      No progress for {stalls} rounds - stopping.")
            break

    if working == base_text:
        log("No usable fix was produced. Try again or fix manually.")
        return 1
    working = strip_auto(working)      # injected pragmas never reach the output
    if working == original:
        log("The only difference was the injected pragmas - nothing to propose.")
        return 1

    proposed = os.path.join(a.output_dir, f"{stem}.proposed{ext}")
    diff_path = os.path.join(a.output_dir, f"{stem}.diff")
    flags_path = os.path.join(a.output_dir, f"{stem}.flags.txt")
    write_text(proposed, working, crlf)
    diff = "".join(difflib.unified_diff(
        original.splitlines(True), working.splitlines(True),
        fromfile=f"a/{base}", tofile=f"b/{base}"))
    with open(diff_path, "w", encoding="utf-8", errors="replace") as f:
        f.write(diff)
    flags = review_flags(original, working)
    with open(flags_path, "w", encoding="utf-8") as f:
        f.write("\n".join(flags) + ("\n" if flags else ""))
    log(f"[4/4] Proposed file: {proposed}\n      Diff saved:    {diff_path}")
    if still_failing:
        log("      WARNING: the proposed version STILL has compile errors.")
    if flags:
        log("      REVIEW: the fix may change behaviour (saved to "
            f"{flags_path}):\n        " + "\n        ".join(flags))

    code = shutil.which("code")
    if a.vscode and code:
        subprocess.Popen([code, "--diff", src, proposed])
    elif a.vscode:
        log("      'code' not on PATH - open the diff manually.")
    else:
        print(diff)

    if a.auto_apply and not still_failing and not flags:
        answer = "y"
    elif sys.stdin.isatty():
        if a.auto_apply and flags:
            log("      --auto-apply skipped: review flags present.")
        answer = input("\nApply this change to the original file? [y/N] ").strip().lower()
    else:
        log("Not a terminal - not applying.")
        return 0
    if answer not in ("y", "yes"):
        log("Not applied. Original file untouched.")
        return 0

    _, _, now_hash = read_text(src)
    if now_hash != orig_hash:
        log("ABORT: the file changed on disk while we were working "
            "(unsaved/edited?). Re-run the task.")
        return 1
    shutil.copy2(src, os.path.join(a.output_dir, stem + ext + ".orig"))
    write_text(src, working, crlf)
    log(f"Applied. Backup: {os.path.join(a.output_dir, stem + ext + '.orig')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
