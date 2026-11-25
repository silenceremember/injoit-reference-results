"""Recalculate the archived occurrence comparisons and the size of changed inputs."""
import csv
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
MODES = ("full", "all", "used")


def measure_inputs(path):
    histories = defaultdict(dict)
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            group = row["doc"], row["mode"]
            step = int(row["step"])
            size = int(row["size_bytes"])
            if step in histories[group] or group[1] not in MODES or size < 0:
                raise ValueError(f"Invalid input history: {group}, step {step}")
            histories[group][step] = row["sha256"], size
    documents = {doc for doc, _ in histories}
    if set(histories) != {(doc, mode) for doc in documents for mode in MODES}:
        raise ValueError("A document is missing an input representation")
    costs = {}
    for group, steps in histories.items():
        if sorted(steps) != list(range(8)):
            raise ValueError(f"Incomplete input history: {group}")
        previous = None
        total = 0
        for step in sorted(steps):
            digest, size = steps[step]
            if digest != previous:
                total += size
            previous = digest
        costs[group] = total
    return costs


def compare(version):
    costs = measure_inputs(DATA / f"{version}-inputs.csv")
    totals = {mode: Counter() for mode in MODES}
    references = {mode: {} for mode in MODES}
    seen = set()
    with gzip.open(DATA / f"{version}.jsonl.gz", "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            doc, step, mode, pos = (row[k] for k in ("doc", "step", "mode", "pos"))
            identity = (doc, step, pos)
            record = (mode, identity)
            if record in seen or (doc, mode) not in costs or step not in range(8):
                raise ValueError(f"Invalid or duplicate observation: {record}")
            seen.add(record)
            expected, observed = row["expected"], row["observed"]
            if expected is None and observed is None:
                raise ValueError(f"No observation at {record}")
            for item in (expected, observed):
                if item is not None and f"{item['start']}-{item['end']}" != pos:
                    raise ValueError(f"Position mismatch at {record}")
            count = totals[mode]
            if expected is None:
                count["extra"] += 1
                continue
            references[mode][identity] = expected
            count["expected"] += 1
            if observed is None:
                count["missing"] += 1
            elif observed == expected:
                count["exact"] += 1
            else:
                count["different"] += 1
    if any(references[mode] != references["full"] for mode in MODES):
        raise ValueError("Modes were compared with different references")
    print(f"\n{version} | mode | expected | exact | different | missing | extra")
    for mode, count in totals.items():
        print(version, mode, *(count[k] for k in
              ("expected", "exact", "different", "missing", "extra")), sep=" | ")
    print("Positions inside term definitions:",
          sum(len(value["state"]["inside"]) for value in references["full"].values()))
    print("Input bytes by document | full | all | used")
    for doc in sorted({doc for doc, _ in costs}):
        print(doc, *(costs[doc, mode] for mode in MODES), sep=" | ")
    print("Total", *(sum(n for (doc, m), n in costs.items() if m == mode)
                      for mode in MODES), sep=" | ")
    return references["full"], totals


if __name__ == "__main__":
    before, _ = compare("before")
    after, counts = compare("after")
    if before != after:
        raise SystemExit("The before/after reference observations differ.")
    if any(c["exact"] != c["expected"] or c["extra"] for c in counts.values()):
        raise SystemExit("At least one corrected observation differs from its reference.")
