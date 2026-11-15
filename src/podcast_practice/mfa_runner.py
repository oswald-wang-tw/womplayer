"""Run the normal MFA CLI and record the precise utterance if alignment fails.

This file runs in the isolated MFA Python environment, so keep imports limited
to the standard library until main() loads that environment's MFA packages.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path


def trace_alignment(original: Callable, failure: Path) -> Callable:
    index = 0

    def tracked(self, utterance, *args, **kwargs):
        nonlocal index
        current = index
        index += 1
        try:
            return original(self, utterance, *args, **kwargs)
        except Exception as exc:
            record = {
                "utterance": current,
                "begin": utterance.segment.begin,
                "end": utterance.segment.end,
                "transcript": utterance.transcript,
                "error": str(exc),
            }
            try:
                temporary = failure.with_suffix(".tmp")
                temporary.write_text(
                    json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                temporary.replace(failure)
            except OSError:
                pass  # Keep the original MFA exception even if diagnostics cannot be written.
            print(
                f"MFA 對齊失敗：第 {current + 1} 段，"
                f"{record['begin']:.3f}–{record['end']:.3f} 秒；"
                f"{utterance.transcript[:200]}",
                flush=True,
            )
            raise

    return tracked


def main() -> None:
    failure = Path(sys.argv.pop(1))
    from kalpy.aligner import KalpyAligner
    from montreal_forced_aligner.command_line.mfa import mfa_cli

    original = KalpyAligner.align_utterance
    KalpyAligner.align_utterance = trace_alignment(original, failure)
    try:
        mfa_cli()
    finally:
        KalpyAligner.align_utterance = original


if __name__ == "__main__":
    main()
