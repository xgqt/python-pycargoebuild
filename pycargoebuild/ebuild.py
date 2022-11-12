import datetime
import re
import tarfile
import typing

from pathlib import Path

import license_expression

from pycargoebuild import __version__
from pycargoebuild.cargo import PackageMetadata, get_package_metadata
from pycargoebuild.format import format_license_var
from pycargoebuild.license import spdx_to_ebuild


EBUILD_TEMPLATE = """\
# Copyright {year} Gentoo Authors
# Distributed under the terms of the GNU General Public License v2

# Autogenerated by pycargoebuild {prog_version}

EAPI=8

CRATES="{crates}"

inherit cargo

DESCRIPTION="{description}"
HOMEPAGE="{homepage}"
SRC_URI="
\t$(cargo_crate_uris)
"

LICENSE="{pkg_license}"
# Dependent crate licenses
LICENSE+="{crate_licenses}"
SLOT="0"
KEYWORDS="~amd64"
"""


def get_CRATES(crate_files: typing.Iterable[Path]) -> str:
    """
    Return the value of CRATES for the given crate list
    """
    if not crate_files:
        return ""
    return "\n" + "\n".join(f"\t{p.name[:-6]}" for p in crate_files) + "\n"


def get_package_LICENSE(pkg_meta: PackageMetadata) -> str:
    """
    Get the value of package's LICENSE string
    """

    spdx = license_expression.get_spdx_licensing()
    if pkg_meta.license is not None:
        parsed_pkg_license = spdx.parse(pkg_meta.license,
                                        validate=True,
                                        strict=True)
        return format_license_var(spdx_to_ebuild(parsed_pkg_license),
                                  'LICENSE="')
    return ""


def get_license_from_crate(path: Path) -> str:
    """
    Read the metadata from specified crate and return its license string
    """

    assert path.name.endswith(".crate")
    with tarfile.open(path, "r:gz") as crate:
        tarf = crate.extractfile(f"{path.name[:-6]}/Cargo.toml")
        if tarf is None:
            raise RuntimeError(f"Cargo.toml not found in {path}")
        with tarf:
            # tarfile.ExFileObject() is IO[bytes] while tomli/tomllib
            # expects BinaryIO -- but it actually is compatible
            # https://github.com/hukkin/tomli/issues/214
            crate_metadata = get_package_metadata(tarf)  # type: ignore
            if crate_metadata.license is None:
                raise RuntimeError(
                    f"Create {path.name} does not specify a license!")
            return crate_metadata.license


def get_crate_LICENSE(crate_files: typing.Iterable[Path]) -> str:
    """
    Get the value of LICENSE string for crates
    """

    spdx = license_expression.get_spdx_licensing()
    crate_licenses = set(map(get_license_from_crate, crate_files))

    # combine crate licenses and simplify the result
    combined_license = " AND ".join(f"( {x} )" for x in crate_licenses)
    parsed_license = spdx.parse(combined_license, validate=True, strict=True)
    if parsed_license is None:
        return ""
    final_license = parsed_license.simplify()
    crate_licenses_str = format_license_var(spdx_to_ebuild(final_license),
                                            'LICENSE+=" ')
    # if it's not a multiline string, we need to prepend " "
    if not crate_licenses_str.startswith("\n"):
        crate_licenses_str = " " + crate_licenses_str
    return crate_licenses_str


def get_ebuild(pkg_meta: PackageMetadata, crate_files: typing.Iterable[Path]
               ) -> str:
    """
    Get ebuild contents for passed contents of Cargo.toml and Cargo.lock.
    """
    return EBUILD_TEMPLATE.format(
        crates=get_CRATES(crate_files),
        crate_licenses=get_crate_LICENSE(crate_files),
        description=pkg_meta.description or "",
        homepage=pkg_meta.homepage or "",
        pkg_license=get_package_LICENSE(pkg_meta),
        prog_version=__version__,
        year=datetime.date.today().year)


def update_ebuild(ebuild: str,
                  pkg_meta: PackageMetadata,
                  crate_files: typing.Iterable[Path]
                  ) -> str:
    """
    Update the CRATES and LICENSE in an existing ebuild
    """

    crates_re = re.compile(r'^CRATES="(.*?)"$', re.DOTALL | re.MULTILINE)
    crates_m = list(crates_re.finditer(ebuild))
    if not crates_m:
        raise RuntimeError("CRATES variable not found in ebuild")
    elif len(crates_m) > 1:
        raise RuntimeError("Multiple CRATES variables found in ebuild")
    crates, = crates_m

    license_re = re.compile(
        r'^# Dependent crate licenses\nLICENSE[+]="(.*?)"$',
        re.DOTALL | re.MULTILINE)
    license_m = list(license_re.finditer(ebuild))
    if not license_m:
        raise RuntimeError("Crate LICENSE+= not found in ebuild (or missing "
                           "marker comment)")
    elif len(license_m) > 1:
        raise RuntimeError("Multiple crate LICENSE+= found in ebuild")
    license, = license_m

    if crates.start(0) < license.start(0):
        if crates.end(0) > license.start(0):
            raise RuntimeError("CRATES and LICENSE+= overlap!")
    else:
        if crates.end(0) < license.start(0):
            raise RuntimeError("CRATES and LICENSE+= overlap!")

    first_match_start = min(crates.start(1), license.start(1))
    first_match_end = min(crates.end(1), license.end(1))
    second_match_start = max(crates.start(1), license.start(1))
    second_match_end = max(crates.end(1), license.end(1))

    return (ebuild[:first_match_start] +
            get_CRATES(crate_files) +
            ebuild[first_match_end:second_match_start] +
            get_crate_LICENSE(crate_files) +
            ebuild[second_match_end:])
