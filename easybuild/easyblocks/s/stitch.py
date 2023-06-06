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
EasyBuild support for stitch, implemented as an easyblock

@author: Caspar van Leeuwen (SURF)
@author: Monica Rotulo (SURF)
"""
import os

import easybuild.tools.toolchain as toolchain
from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.filetools import apply_regex_substitutions, change_dir, copy_file
from easybuild.tools.run import run_cmd

DEFAULT_BUILD_CMD = 'make'
DEFAULT_BUILD_TARGET = ''
DEFAULT_TEST_CMD = 'make'


class EB_stitch(EasyBlock):
    """Support for building/installing stitch."""

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to ConfigureMake."""
        extra_vars = EasyBlock.extra_options(extra=extra_vars)
        extra_vars.update({
            'build_cmd': [DEFAULT_BUILD_CMD, "Build command to use", CUSTOM],
            'build_cmd_targets': [DEFAULT_BUILD_TARGET, "Target name (string) or list of target names to build",
                                  CUSTOM],
            'test_cmd': [DEFAULT_TEST_CMD, "Test command to use ('runtest' value is appended)", CUSTOM],
        })
        return extra_vars

    def configure_step(self):
        """Configure stitch build: locate the template makefile, and patch it."""

        # Currently, Stitch is part of the spparks source code. This might change in future versions,
        # so the srdir_stitch may change
        self.srcdir_stitch = os.path.join(self.cfg['start_dir'], 'lib', 'stitch', 'libstitch')

        # To configure libstitch, we alter the makefile
        makefile_stitch = os.path.join(self.srcdir_stitch, 'Makefile')

        if self.toolchain.options.get('usempi', False):
            cc = os.environ['MPICC']
            cxx = os.environ['MPICXX']
        else:
            cc = os.environ['CC']
            cxx = os.environ['CXX']

        # Makefile doesn't contain any flags. Easiest way to add them is just append to the compiler command...
        if self.toolchain.options.get('optarch', False):
            cc += ' %s' % self.toolchain.get_flag('optarch')
            cxx += ' %s' % self.toolchain.get_flag('optarch')

        regex_subs_stitch = [
            (r"^(CC\s*=\s*).*$", r"\1%s" % cc),
            (r"^(CXX\s*=\s*).*$", r"\1%s" % cxx)
        ]
        apply_regex_substitutions(makefile_stitch, regex_subs_stitch)

    def test_step(self):
        """
        Test the compilation
        - typically: make stitch_test && mpirun -np 4 stitch_test
        """

        test_cmd = self.cfg.get('test_cmd') or DEFAULT_TEST_CMD
        if self.cfg['runtest'] or test_cmd != DEFAULT_TEST_CMD:
            cmd = ' '.join([
                self.cfg['pretestopts'],
                test_cmd,
                self.cfg['runtest'],
                self.cfg['testopts'],
            ])
            (out, _) = run_cmd(cmd, log_all=True, simple=False)

            return out

    def build_step(self, verbose=False, path=None):
        """
        Start the actual build
        - typical: make -j X
        """

        # Change to stitch sourcedir. This may need to be removed if Stitch is ever separated from the spparks sources
        change_dir(self.srcdir_stitch)

        paracmd = ''
        if self.cfg['parallel']:
            paracmd = "-j %s" % self.cfg['parallel']

        targets = self.cfg.get('build_cmd_targets') or DEFAULT_BUILD_TARGET
        # ensure strings are converted to list
        targets = [targets] if isinstance(targets, str) else targets

        for target in targets:
            cmd = ' '.join([
                self.cfg['prebuildopts'],
                self.cfg.get('build_cmd') or DEFAULT_BUILD_CMD,
                target,
                paracmd,
                self.cfg['buildopts'],
            ])
            self.log.info("Building target '%s'", target)

            (out, _) = run_cmd(cmd, path=path, log_all=True, simple=False, log_output=verbose)

        return out

    def install_step(self):
        """Install by copying files."""

        self.log.debug("Installing stitch by copying files")

        headers = ['stitch.h', 'sqlite3.h']
        libs = ['libstitch.a']

        for header in headers:
            copy_file(os.path.join(self.srcdir_stitch, header), os.path.join(self.installdir, 'include', header))

        for lib in libs:
            copy_file(os.path.join(self.srcdir_stitch, lib), os.path.join(self.installdir, 'lib', lib))

