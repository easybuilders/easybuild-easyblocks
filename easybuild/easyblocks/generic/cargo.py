##
# Copyright 2009-2023 Ghent University
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
"""

import os

import easybuild.tools.environment as env
import easybuild.tools.systemtools as systemtools
from easybuild.tools.build_log import EasyBuildError
from easybuild.framework.easyconfig import CUSTOM
from easybuild.framework.extensioneasyblock import ExtensionEasyBlock
from easybuild.tools.filetools import extract_file, change_dir
from easybuild.tools.run import run_cmd
from easybuild.tools.config import build_option
from easybuild.tools.filetools import write_file, compute_checksum
from easybuild.tools.toolchain.compiler import OPTARCH_GENERIC

CRATESIO_SOURCE = "https://crates.io/api/v1/crates"


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
        env.setvar('CARGO_HOME', self.cargo_home)
        env.setvar('RUSTC', 'rustc')
        env.setvar('RUSTDOC', 'rustdoc')
        env.setvar('RUSTFMT', 'rustfmt')
        env.setvar('RUSTFLAGS', self.rustc_optarch())
        env.setvar('RUST_LOG', 'DEBUG')
        env.setvar('RUST_BACKTRACE', '1')

        # Populate sources from "crates" list of tuples (only once)
        if self.cfg['crates']:
            # copy list of crates, so we can wipe 'crates' easyconfig parameter,
            # to avoid that creates are processed into 'sources' easyconfig parameter again
            # when easyblock is initialized again using same parsed easyconfig
            # (for example when check_sha256_checksums function is called, like in easyconfigs test suite)
            self.crates = self.cfg['crates'][:]
            sources = []
            for crate_info in self.cfg['crates']:
                if len(crate_info) == 2:
                    crate, version = crate_info
                    sources.append({
                        'download_filename': crate + '/' + version + '/download',
                        'filename': crate + '-' + version + '.tar.gz',
                        'source_urls': [CRATESIO_SOURCE],
                        'alt_location': 'crates.io',
                    })
                else:
                    crate, version, repo, rev = crate_info
                    url, repo_name_git = repo.rsplit('/', maxsplit=1)
                    sources.append({
                        'git_config': {'url': url, 'repo_name': repo_name_git[:-4], 'commit': rev},
                        'filename': crate + '-' + version + '.tar.gz',
                        'source_urls': [CRATESIO_SOURCE],
                    })

            self.cfg.update('sources', sources)

            # set 'crates' easyconfig parameter to empty list to prevent re-processing into sources
            self.cfg['crates'] = []

    def extract_step(self):
        """
        Unpack the source files and populate them with required .cargo-checksum.json if offline
        """
        if self.cfg['offline']:
            self.log.info("Setting vendored crates dir")
            # Replace crates-io with vendored sources using build dir wide toml file in CARGO_HOME
            # because the rust source subdirectories might differ with python packages
            config_toml = os.path.join(self.cargo_home, 'config.toml')
            write_file(config_toml, '[source.vendored-sources]\ndirectory = "%s"\n\n' % self.builddir, append=True)
            write_file(config_toml, '[source.crates-io]\nreplace-with = "vendored-sources"\n\n', append=True)

            # also vendor sources from other git sources (could be many crates for one git source)
            git_sources = set()
            for crate_info in self.crates:
                if len(crate_info) == 4:
                    _, _, repo, rev = crate_info
                    git_sources.add((repo, rev))
            for repo, rev in git_sources:
                write_file(config_toml, '[source."%s"]\ngit = "%s"\nrev = "%s"\n'
                                        'replace-with = "vendored-sources"\n\n' % (repo, repo, rev), append=True)

            # Use environment variable since it would also be passed along to builds triggered via python packages
            env.setvar('CARGO_NET_OFFLINE', 'true')

        # More work is needed here for git sources to work, especially those repos with multiple packages.
        for src in self.src:
            existing_dirs = set(os.listdir(self.builddir))
            self.log.info("Unpacking source %s" % src['name'])
            srcdir = extract_file(src['path'], self.builddir, cmd=src['cmd'],
                                  extra_options=self.cfg['unpack_options'], change_into_dir=False)
            change_dir(srcdir)
            if srcdir:
                self.src[self.src.index(src)]['finalpath'] = srcdir
            else:
                raise EasyBuildError("Unpacking source %s failed", src['name'])

            # Create checksum file for all sources required by vendored crates.io sources
            new_dirs = set(os.listdir(self.builddir)) - existing_dirs
            if self.cfg['offline'] and len(new_dirs) == 1:
                cratedir = new_dirs.pop()
                self.log.info('creating .cargo-checksums.json file for : %s', cratedir)
                chksum = compute_checksum(src['path'], checksum_type='sha256')
                chkfile = os.path.join(self.builddir, cratedir, '.cargo-checksum.json')
                write_file(chkfile, '{"files":{},"package":"%s"}' % chksum)

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

    app_name = cargo_toml['package']['name']
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
                    # Lock file has revision#revision in the url for some reason.
                    crates.append((name, version, dep['source'].rsplit('#', maxsplit=1)[0]))
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
            print("    ('" + "', '".join(crate_info) + "'),")
        print(']')
