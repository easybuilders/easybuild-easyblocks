##
# Copyright 2009-2024 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# https://github.com/easybuilders/easybuild
#
# EasyBuild is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation v2.
#
# EasyBuild is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with EasyBuild.  If not, see <http://www.gnu.org/licenses/>.
##
"""
EasyBuild support for installing Cargo packages (Rust lang package system)

@author: Mikael Oehman (Chalmers University of Technology)
@author: Alex Domingo (Vrije Universiteit Brussel)
"""

import os
import re

import easybuild.tools.environment as env
import easybuild.tools.systemtools as systemtools
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.framework.easyconfig import CUSTOM
from easybuild.framework.extensioneasyblock import ExtensionEasyBlock
from easybuild.tools.filetools import extract_file, change_dir
from easybuild.tools.run import run_cmd
from easybuild.tools.config import build_option
from easybuild.tools.filetools import compute_checksum, mkdir, write_file
from easybuild.tools.toolchain.compiler import OPTARCH_GENERIC

CRATESIO_SOURCE = "https://crates.io/api/v1/crates"

CONFIG_TOML_SOURCE_VENDOR = """
[source.vendored-sources]
directory = "{vendor_dir}"

[source.crates-io]
replace-with = "vendored-sources"

"""

CONFIG_TOML_PATCH_GIT = """
[patch."{repo}"]
{crates}
"""
CONFIG_TOML_PATCH_GIT_CRATES = """{0} = {{ path = "{1}" }}
"""

CARGO_CHECKSUM_JSON = '{{"files": {{}}, "package": "{chksum}"}}'


class Cargo(ExtensionEasyBlock):
    """Support for installing Cargo packages (Rust)"""

    @staticmethod
    def extra_options(extra_vars=None):
        """Define extra easyconfig parameters specific to Cargo"""
        extra_vars = ExtensionEasyBlock.extra_options(extra_vars)
        extra_vars.update({
            'enable_tests': [True, "Enable building of tests", CUSTOM],
            'offline': [True, "Build offline", CUSTOM],
            'lto': [None, "Override default LTO flag ('fat', 'thin', 'off')", CUSTOM],
            'crates': [[], "List of (crate, version, [repo, rev]) tuples to use", CUSTOM],
        })

        return extra_vars

    @staticmethod
    def crate_src_filename(pkg_name, pkg_version, *args):
        """Crate tarball filename based on package name and version"""
        return "{0}-{1}.tar.gz".format(pkg_name, pkg_version)

    @staticmethod
    def crate_download_filename(pkg_name, pkg_version, *args):
        """Crate download filename based on package name and version"""
        return "{0}/{1}/download".format(pkg_name, pkg_version)

    def rustc_optarch(self):
        """Determines what architecture to target.
        Translates GENERIC optarch, and respects rustc specific optarch.
        General optarchs are ignored as there is no direct translation.
        """
        if systemtools.X86_64 == systemtools.get_cpu_architecture():
            generic = '-C target-cpu=x86-64'
        else:
            generic = '-C target-cpu=generic'

        optimal = '-C target-cpu=native'

        optarch = build_option('optarch')
        if optarch:
            if isinstance(optarch, dict):
                if 'rustc' in optarch:
                    rust_optarch = optarch['rustc']
                    if rust_optarch == OPTARCH_GENERIC:
                        return generic
                    else:
                        return '-' + rust_optarch
                self.log.info("no rustc information in the optarch dict, so using %s" % optimal)
            elif optarch == OPTARCH_GENERIC:
                return generic
            else:
                self.log.warning("optarch is ignored as there is no translation for rustc, so using %s" % optimal)
        return optimal

    def __init__(self, *args, **kwargs):
        """Constructor for Cargo easyblock."""
        super(Cargo, self).__init__(*args, **kwargs)
        self.cargo_home = os.path.join(self.builddir, '.cargo')
        self.vendor_dir = os.path.join(self.builddir, 'easybuild_vendor')
        env.setvar('CARGO_HOME', self.cargo_home)
        env.setvar('RUSTC', 'rustc')
        env.setvar('RUSTDOC', 'rustdoc')
        env.setvar('RUSTFMT', 'rustfmt')
        env.setvar('RUSTFLAGS', self.rustc_optarch())
        env.setvar('RUST_LOG', 'DEBUG')
        env.setvar('RUST_BACKTRACE', '1')

        # Populate sources from "crates" list of tuples (only once)
        if self.cfg['crates']:
            # Move 'crates' list from easyconfig parameter to property,
            # to avoid that creates are processed into 'sources' easyconfig parameter again
            # when easyblock is initialized again using the same parsed easyconfig
            # (for example when check_sha256_checksums function is called, like in easyconfigs test suite)
            self.crates = self.cfg['crates']
            self.cfg['crates'] = []
            sources = []
            for crate_info in self.crates:
                if len(crate_info) == 2:
                    sources.append({
                        'download_filename': self.crate_download_filename(*crate_info),
                        'filename': self.crate_src_filename(*crate_info),
                        'source_urls': [CRATESIO_SOURCE],
                        'alt_location': 'crates.io',
                    })
                else:
                    crate, version, repo, rev = crate_info
                    url, repo_name = repo.rsplit('/', maxsplit=1)
                    if repo_name.endswith('.git'):
                        repo_name = repo_name[:-4]
                    sources.append({
                        'git_config': {'url': url, 'repo_name': repo_name, 'commit': rev},
                        'filename': self.crate_src_filename(crate, version),
                    })

            self.cfg.update('sources', sources)

    def extract_step(self):
        """
        Unpack the source files and populate them with required .cargo-checksum.json if offline
        """
        mkdir(self.vendor_dir)

        vendor_crates = {self.crate_src_filename(*crate): crate for crate in self.crates}
        git_sources = {crate[2]: [] for crate in self.crates if len(crate) == 4}

        for src in self.src:
            extraction_dir = self.builddir
            # Extract dependency crates into vendor subdirectory, separate from sources of main package
            if src['name'] in vendor_crates:
                extraction_dir = self.vendor_dir

            self.log.info("Unpacking source of %s", src['name'])
            existing_dirs = set(os.listdir(extraction_dir))
            crate_dir = None
            src_dir = extract_file(src['path'], extraction_dir, cmd=src['cmd'],
                                   extra_options=self.cfg['unpack_options'], change_into_dir=False)
            new_extracted_dirs = set(os.listdir(extraction_dir)) - existing_dirs

            if len(new_extracted_dirs) == 1:
                # Expected crate tarball with 1 folder
                crate_dir = new_extracted_dirs.pop()
                src_dir = os.path.join(extraction_dir, crate_dir)
                self.log.debug("Unpacked sources of %s into: %s", src['name'], src_dir)
            elif len(new_extracted_dirs) == 0:
                # Extraction went wrong
                raise EasyBuildError("Unpacking sources of '%s' failed", src['name'])
            # TODO: properly handle case with multiple extracted folders
            # this is currently in a grey area, might still be used by cargo

            change_dir(src_dir)
            self.src[self.src.index(src)]['finalpath'] = src_dir

            if self.cfg['offline'] and crate_dir:
                # Create checksum file for extracted sources required by vendored crates.io sources
                self.log.info('creating .cargo-checksums.json file for : %s', crate_dir)
                chksum = compute_checksum(src['path'], checksum_type='sha256')
                chkfile = os.path.join(extraction_dir, crate_dir, '.cargo-checksum.json')
                write_file(chkfile, CARGO_CHECKSUM_JSON.format(chksum=chksum))
                # Add path to extracted sources for any crate from a git repo
                try:
                    crate_name, _, crate_repo, _ = vendor_crates[src['name']]
                except (ValueError, KeyError):
                    pass
                else:
                    self.log.debug("Sources of %s belong to git repo: %s", src['name'], crate_repo)
                    git_src_dir = (crate_name, src_dir)
                    git_sources[crate_repo].append(git_src_dir)

        if self.cfg['offline']:
            self.log.info("Setting vendored crates dir for offline operation")
            config_toml = os.path.join(self.cargo_home, 'config.toml')
            # Replace crates-io with vendored sources using build dir wide toml file in CARGO_HOME
            # because the rust source subdirectories might differ with python packages
            self.log.debug("Writting config.toml entry for vendored crates from crate.io")
            write_file(config_toml, CONFIG_TOML_SOURCE_VENDOR.format(vendor_dir=self.vendor_dir), append=True)

            # also vendor sources from other git sources (could be many crates for one git source)
            for git_repo, repo_crates in git_sources.items():
                self.log.debug("Writting config.toml entry for git repo: %s", git_repo)
                config_crates = ''.join([CONFIG_TOML_PATCH_GIT_CRATES.format(*crate) for crate in repo_crates])
                write_file(config_toml, CONFIG_TOML_PATCH_GIT.format(repo=git_repo, crates=config_crates), append=True)

            # Use environment variable since it would also be passed along to builds triggered via python packages
            env.setvar('CARGO_NET_OFFLINE', 'true')

    def configure_step(self):
        """Empty configuration step."""
        pass

    @property
    def profile(self):
        return 'debug' if self.toolchain.options.get('debug', None) else 'release'

    def build_step(self):
        """Build with cargo"""
        parallel = ''
        if self.cfg['parallel']:
            parallel = "-j %s" % self.cfg['parallel']

        tests = ''
        if self.cfg['enable_tests']:
            tests = "--tests"

        lto = ''
        if self.cfg['lto'] is not None:
            lto = '--config profile.%s.lto=\\"%s\\"' % (self.profile, self.cfg['lto'])

        run_cmd('rustc --print cfg', log_all=True, simple=True)  # for tracking in log file
        cmd = ' '.join([
            self.cfg['prebuildopts'],
            'cargo build',
            '--profile=' + self.profile,
            lto,
            tests,
            parallel,
            self.cfg['buildopts'],
        ])
        run_cmd(cmd, log_all=True, simple=True)

    def test_step(self):
        """Test with cargo"""
        if self.cfg['enable_tests']:
            cmd = ' '.join([
                self.cfg['pretestopts'],
                'cargo test',
                '--profile=' + self.profile,
                self.cfg['testopts'],
            ])
            run_cmd(cmd, log_all=True, simple=True)

    def install_step(self):
        """Install with cargo"""
        cmd = ' '.join([
            self.cfg['preinstallopts'],
            'cargo install',
            '--profile=' + self.profile,
            '--root=' + self.installdir,
            '--path=.',
            self.cfg['installopts'],
        ])
        run_cmd(cmd, log_all=True, simple=True)


def generate_crate_list(sourcedir):
    """Helper for generating crate list"""
    import toml

    cargo_toml = toml.load(os.path.join(sourcedir, 'Cargo.toml'))
    cargo_lock = toml.load(os.path.join(sourcedir, 'Cargo.lock'))

    try:
        app_name = cargo_toml['package']['name']
    except KeyError:
        app_name = os.path.basename(os.path.abspath(sourcedir))
        print_warning('Did not find a [package] name= entry. Assuming it is the folder name: ' + app_name)
    deps = cargo_lock['package']

    app_in_cratesio = False
    crates = []
    other_crates = []
    for dep in deps:
        name = dep['name']
        version = dep['version']
        if 'source' in dep:
            if name == app_name:
                app_in_cratesio = True  # exclude app itself, needs to be first in crates list or taken from pypi
            else:
                if dep['source'] == 'registry+https://github.com/rust-lang/crates.io-index':
                    crates.append((name, version))
                else:
                    # Lock file has revision#revision in the url
                    url, rev = dep['source'].rsplit('#', maxsplit=1)
                    for prefix in ('registry+', 'git+'):
                        if url.startswith(prefix):
                            url = url[len(prefix):]
                    # Remove branch name if present
                    url = re.sub(r'\?branch=\w+$', '', url)
                    crates.append((name, version, url, rev))
        else:
            other_crates.append((name, version))
    return app_in_cratesio, crates, other_crates


if __name__ == '__main__':
    import sys
    app_in_cratesio, crates, other = generate_crate_list(sys.argv[1])
    print(other)
    if app_in_cratesio or crates:
        print('crates = [')
        if app_in_cratesio:
            print('    (name, version),')
        for crate_info in crates:
            print("    %s," % str(crate_info))
        print(']')
