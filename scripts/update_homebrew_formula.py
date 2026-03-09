#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Dict, Tuple

RELEASE_API_URL = "https://api.github.com/repos/router-for-me/CLIProxyAPI/releases/latest"
FORMULA_PATH = Path(__file__).resolve().parents[1] / "Formula" / "cliproxyapi.rb"
ASSET_NAMES = {
    "darwin_arm64": "CLIProxyAPI_{version}_darwin_arm64.tar.gz",
    "darwin_amd64": "CLIProxyAPI_{version}_darwin_amd64.tar.gz",
    "linux_arm64": "CLIProxyAPI_{version}_linux_arm64.tar.gz",
    "linux_amd64": "CLIProxyAPI_{version}_linux_amd64.tar.gz",
}
SHA_LABEL_TO_KEY = {
    "darwin-arm": "darwin_arm64",
    "darwin-amd": "darwin_amd64",
    "linux-arm": "linux_arm64",
    "linux-amd": "linux_amd64",
}


def parse_checksums(checksums_text: str, version: str) -> Dict[str, str]:
    expected_files = {
        template.format(version=version): key for key, template in ASSET_NAMES.items()
    }
    result: Dict[str, str] = {}

    for line in checksums_text.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        checksum, filename = parts
        key = expected_files.get(filename)
        if key:
            result[key] = checksum

    missing = sorted(set(expected_files.values()) - set(result))
    if missing:
        raise ValueError(f"Missing checksums for: {', '.join(missing)}")

    return result


def update_formula_text(formula_text: str, version: str, checksums: Dict[str, str]) -> Tuple[str, bool]:
    updated_text = re.sub(r'version ".*?"', f'version "{version}"', formula_text, count=1)

    for label, key in SHA_LABEL_TO_KEY.items():
        pattern = rf'sha256 "(?P<value>[^"]+)"(?=.*{label})'
        if label in updated_text:
            updated_text = re.sub(pattern, f'sha256 "{checksums[key]}"', updated_text, count=1, flags=re.DOTALL)

    # Fallback for current formula structure without explicit labels nearby.
    sha_values = re.findall(r'sha256 "([^"]+)"', updated_text)
    if len(sha_values) >= 4:
        replacements = [
            checksums["darwin_arm64"],
            checksums["darwin_amd64"],
            checksums["linux_arm64"],
            checksums["linux_amd64"],
        ]
        updated_text = re.sub(
            r'sha256 ".*?"',
            lambda match, repl_iter=iter(replacements): f'sha256 "{next(repl_iter)}"',
            updated_text,
            count=4,
        )

    return updated_text, updated_text != formula_text


def gh_available() -> bool:
    return shutil.which("gh") is not None


def run_gh_api(endpoint: str, *, accept: str | None = None) -> bytes:
    command = ["gh", "api"]
    if accept:
        command.extend(["-H", f"Accept: {accept}"])
    command.append(endpoint)
    result = subprocess.run(command, check=True, capture_output=True)
    return result.stdout


def api_endpoint_from_url(url: str) -> str | None:
    prefix = "https://api.github.com/"
    if url.startswith(prefix):
        return url[len(prefix):]
    return None


def fetch_json(url: str) -> dict:
    endpoint = api_endpoint_from_url(url)
    if endpoint and gh_available():
        try:
            return json.loads(run_gh_api(endpoint).decode("utf-8"))
        except subprocess.CalledProcessError:
            pass

    with urllib.request.urlopen(url) as response:
        return json.load(response)


def fetch_text(url: str, *, accept: str | None = None) -> str:
    endpoint = api_endpoint_from_url(url)
    if endpoint and gh_available():
        try:
            return run_gh_api(endpoint, accept=accept).decode("utf-8")
        except subprocess.CalledProcessError:
            pass

    request = urllib.request.Request(url)
    if accept:
        request.add_header("Accept", accept)

    with urllib.request.urlopen(request) as response:
        return response.read().decode("utf-8")


def update_formula_file(formula_path: Path = FORMULA_PATH) -> bool:
    release = fetch_json(RELEASE_API_URL)
    version = release["tag_name"].removeprefix("v")

    checksums_asset = next(
        (asset for asset in release.get("assets", []) if asset.get("name") == "checksums.txt"),
        None,
    )
    if checksums_asset is None:
        raise ValueError("checksums.txt asset not found in latest release")

    checksums = parse_checksums(
        fetch_text(checksums_asset["url"], accept="application/octet-stream"),
        version,
    )

    original_text = formula_path.read_text()
    updated_text, changed = update_formula_text(original_text, version, checksums)
    if changed:
        formula_path.write_text(updated_text)

    return changed


def main() -> int:
    changed = update_formula_file()
    if changed:
        print("Formula updated")
    else:
        print("Formula already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
