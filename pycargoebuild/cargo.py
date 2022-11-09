import sys
import typing

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


class Crate(typing.NamedTuple):
    name: str
    version: str
    checksum: str


Crates = typing.List[Crate]


class PackageMetadata(typing.NamedTuple):
    name: str
    version: str
    license: str
    description: typing.Optional[str]
    homepage: typing.Optional[str]


def cargo_to_spdx(license_str: str) -> str:
    """
    Convert deprecated Cargo license string to SPDX-2.0, if necessary.
    """
    return license_str.replace("/", " OR ")


def get_crates(f: typing.BinaryIO, exclude: list[str]) -> Crates:
    """Read crate list from the open ``Cargo.lock`` file"""
    cargo_lock = tomllib.load(f)
    assert cargo_lock["version"] == 3
    return [Crate(name=p["name"], version=p["version"], checksum=p["checksum"])
            for p in cargo_lock["package"]
            if p["name"] not in exclude]


def get_package_metadata(f: typing.BinaryIO) -> PackageMetadata:
    """Read package from the open ``Cargo.toml`` file"""
    cargo_toml = tomllib.load(f)
    pkg_meta = cargo_toml["package"]
    assert "license_file" not in pkg_meta  # TODO
    return PackageMetadata(name=pkg_meta["name"],
                           version=pkg_meta["version"],
                           license=cargo_to_spdx(pkg_meta["license"]),
                           description=pkg_meta.get("description"),
                           homepage=pkg_meta.get("homepage"))
