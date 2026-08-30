import pathlib
import sys


EXPECTED = {
    "Seed": "00000000-0000-4000-8000-000000000007",
    "SourceDateEpoch": "0",
}


def main():
    path = pathlib.Path(sys.argv[1])
    section = None
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        name, separator, value = line.partition("=")
        if separator and ((section == "Output" and name == "Seed") or
                          (section == "Content" and name == "SourceDateEpoch")):
            values[name] = value
    if values != EXPECTED:
        raise AssertionError("tracer determinism settings changed: %r" % values)
    print("tracer determinism settings: Seed=%s SourceDateEpoch=%s" %
          (values["Seed"], values["SourceDateEpoch"]))


if __name__ == "__main__":
    main()
