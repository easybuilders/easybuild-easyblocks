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
from easybuild.framework.easyconfig import CUSTOM
from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.run import run_cmd
from easybuild.tools.config import build_option
from easybuild.tools.filetools import write_file, compute_checksum
# from easybuild.tools.filetools import remove_file

CRATESIO_SOURCE = "https://crates.io/api/v1/crates"


class Cargo(EasyBlock):
    """Support for installing Cargo packages (Rust)"""

    @staticmethod
    def extra_options(extra_vars=None):
        """Define extra easyconfig parameters specific to Cargo"""
        extra_vars = EasyBlock.extra_options(extra_vars)
        extra_vars.update({
            # 'tests': [True, "Build tests", CUSTOM],
            'offline': [True, "Build tests", CUSTOM],
            'lto': [False, "Build with link time optimization", CUSTOM],
        })

        # if 'source_urls' not in extra_vars:
        #    extra_vars['source_urls'] = [CRATESIO_SOURCE]

        # extra_vars['download_filename_template'] = '%(name)s/%(version)s/download'

        return extra_vars

    def __init__(self, *args, **kwargs):
        """Constructor for Simpack easyblock."""
        super(Cargo, self).__init__(*args, **kwargs)
        env.setvar('CARGO_HOME', os.path.join(self.builddir, '.cargo'))
        env.setvar('RUSTC', 'rustc')
        env.setvar('RUSTDOC', 'rustdoc')
        env.setvar('RUSTFMT', 'rustfmt')
        optarch = build_option('optarch')
        if not optarch:
            optarch = 'native'
        env.setvar('RUSTFLAGS', '-C target-cpu=%s' % optarch)
        env.setvar('RUST_LOG', 'DEBUG')
        env.setvar('RUST_BACKTRACE', '1')

    def configure_step(self):
        pass

    def extract_step(self):
        """Populate all vendored deps with required .cargo-checksum.json"""
        EasyBlock.extract_step(self)
        for source in self.src:
            dirname = source["name"].rsplit('.', maxsplit=2)[0]
            self.log.info('creating .cargo-checksums.json file for : %s', dirname)
            chksum = compute_checksum(source['path'], checksum_type='sha256')
            chkfile = '%s/%s/.cargo-checksum.json' % (self.builddir, dirname)
            write_file(chkfile, '{"files":{},"package":"%s"}' % chksum)

    @property
    def profile(self):
        return 'debug' if self.toolchain.options.get('debug', None) else 'release'

    def build_step(self):
        """Build with cargo"""
        parallel = ''
        if self.cfg['parallel']:
            parallel = "-j %s" % self.cfg['parallel']

        tests = ''
        if self.cfg['tests']:
            parallel = "--tests"

        offline = ''
        if self.cfg['offline']:
            parallel = "--offline"

        lto = ''
        if self.cfg['lto']:
            parallel = '--config profile.%s.lto=true' % self.profile

        run_cmd('rustc --print cfg', log_all=True, simple=True)  # for tracking in log file
        # attempt to circumvent the checksum-check that cargo build does, but it still looks for the checksum json file
        # remove_file('Cargo.lock')
        # Can't figure out how to supply this via command line
        write_file('.cargo/config.toml', '[source.crates-io]\ndirectory=".."', append=True)
        cmd = '%s cargo build --profile=%s %s %s %s %s %s' % (
            self.cfg['prebuildopts'], self.profile, offline, lto, tests, parallel, self.cfg['buildopts'])
        run_cmd(cmd, log_all=True, simple=True)

    def test_step(self):
        """Test with cargo"""
        if self.cfg['tests']:
            cmd = "%s cargo test --profile=%s %s" % (self.cfg['pretestopts'], self.profile, self.cfg['testopts'])
            run_cmd(cmd, log_all=True, simple=True)

    def install_step(self):
        """Install with cargo"""
        cmd = "%s cargo install --profile=%s --offline --root %s --path . %s" % (
            self.cfg['preinstallopts'], self.profile, self.installdir, self.cfg['installopts'])
        run_cmd(cmd, log_all=True, simple=True)
