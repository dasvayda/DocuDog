#!/usr/bin/env python3
"""Download gated LiteRT-LM Gemma bundles from Hugging Face after authentication.

Hugging Face pages often show "No code snippets available" for newer repos.
CLI flow (run once in a terminal — interactive):

  pip install -U "huggingface_hub[cli]"
  hf auth login

Or (classic):

  huggingface-cli login

Before downloading, open the model page in a browser, sign in, and accept the
Gemma license so your account is granted access.

Then run:

  python tools/download_litert_gemma.py

Default repo: google/gemma-3n-E2B-it-litert-lm (LiteRT-LM bundle).

Optional:

  set HF_TOKEN=hf_...   # token from https://huggingface.co/settings/tokens
  python tools/download_litert_gemma.py --repo google/other-litert-lm-repo

The script writes under C:\\my-own-project\\local-llm\\<repo_last_segment>\\
(or $DOCUDOG_LLM_HOME) and prints the first *.litertlm path (if any) for
config.json -> model.litert_lm_bundle_path. Pass --dest to override.

Note: repos like google/gemma-2b are often Safetensors/Transformers weights,
not LiteRT bundles. DocuDog's litert_lm path must be a .litertlm file; if this
snapshot has none, use a LiteRT-LM published repo or another backend.
"""

from __future__ import annotations

import argparse
import glob
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Download a Hugging Face model snapshot (LiteRT .litertlm if present).")
    parser.add_argument(
        "--repo",
        default="google/gemma-3n-E2B-it-litert-lm",
        help="Hugging Face repo id (gated; requires hf auth + license acceptance).",
    )
    parser.add_argument(
        "--dest",
        default="",
        help="Destination folder. Default: %%DOCUDOG_LLM_HOME%%/<repo> or C:\\my-own-project\\local-llm\\<repo>.",
    )
    args = parser.parse_args()

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("Install: pip install huggingface_hub", file=sys.stderr)
        return 1

    repo_tail = args.repo.split("/")[-1]
    llm_home = os.environ.get("DOCUDOG_LLM_HOME") or r"C:\my-own-project\local-llm"
    dest = args.dest or os.path.join(llm_home, repo_tail)
    os.makedirs(dest, exist_ok=True)

    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    try:
        snapshot_download(
            repo_id=args.repo,
            local_dir=dest,
            token=token,
        )
    except Exception as e:
        print(
            "Download failed. Typical fixes:\n"
            "  1) Run: hf auth login   (or huggingface-cli login)\n"
            "  2) In browser: accept Gemma license on the model page while logged in.\n"
            "  3) Or set HF_TOKEN to a read token with access to the repo.\n"
            f"\nDetail: {e}",
            file=sys.stderr,
        )
        return 1

    litert = sorted(glob.glob(os.path.join(dest, "**", "*.litertlm"), recursive=True))
    if not litert:
        litert = sorted(glob.glob(os.path.join(dest, "*.litertlm")))
    print(f"Downloaded repo to: {dest}")
    if litert:
        pick = litert[0]
        print("Use this path in config.json -> model.litert_lm_bundle_path :")
        print(os.path.normpath(pick))
        if len(litert) > 1:
            print("\nOther .litertlm files:")
            for p in litert[1:]:
                print(os.path.normpath(p))
    else:
        print("No .litertlm file under:", dest)
        print(
            "DocuDog inference.py expects a LiteRT-LM .litertlm bundle.\n"
            "This snapshot did not contain any *.litertlm files; check the repo file list on Hugging Face\n"
            "or pick another LiteRT-LM release."
        )
    print('\nSet "use_mock": false in config.json when ready (only if you have a .litertlm path).')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
