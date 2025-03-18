##
# Copyright 2015-2025 Ghent University
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
EasyBuild support for Molpro, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
"""
import glob
import os
import shutil
import re

from easybuild.easyblocks.generic.binary import Binary
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools import LooseVersion
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.filetools import apply_regex_substitutions, change_dir, mkdir, read_file, symlink
from easybuild.tools.run import run_shell_cmd


class EB_Molpro(ConfigureMake, Binary):
    """Support for building and installing Molpro."""

    @staticmethod
    def extra_options():
        """Define custom easyconfig parameters for Molpro."""
        # Combine extra variables from Binary and ConfigureMake easyblocks as
        # well as those needed for Molpro specifically
        extra_vars = Binary.extra_options()
        extra_vars = ConfigureMake.extra_options(extra_vars)
        extra_vars.update({
            'precompiled_binaries': [False, "Are we installing precompiled binaries?", CUSTOM],
        })
        return EasyBlock.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Easyblock constructor, initialize class variables specific to Molpro and check on license token."""
        super(EB_Molpro, self).__init__(*args, **kwargs)

        self.full_prefix = ''  # no None, to make easyblock compatible with --module-only
        self.orig_launcher = None

        self.cleanup_token_symlink = False
        self.license_token = os.path.join(os.path.expanduser('~'), '.molpro', 'token')

        # custom paths in module load environment
        # add glob patterns for all possible locations of executables, non-existent ones will be ignored
        self.module_load_environment.PATH = [
            'bin',
            '*/bin',
            '*/utilities',
        ]

    def extract_step(self):
        """Extract Molpro source files, or just copy in case of binary install."""
        if self.cfg['precompiled_binaries']:
            Binary.extract_step(self)
        else:
            ConfigureMake.extract_step(self)

    def configure_step(self):
        """Custom configuration procedure for Molpro: use 'configure -batch'."""

        if not os.path.isfile(self.license_token):
            if self.cfg['license_file'] is not None and os.path.isfile(self.cfg['license_file']):
                # put symlink in place to specified license file in $HOME/.molpro/token
                # other approaches (like defining $MOLPRO_KEY) don't seem to work
                self.cleanup_token_symlink = True
                mkdir(os.path.dirname(self.license_token))
                symlink(self.cfg['license_file'], self.license_token)
                self.log.debug("Symlinked %s to %s", self.cfg['license_file'], self.license_token)
            else:
                self.log.warning("No licence token found at either %s or via 'license_file'",
                                 self.license_token)

        # Only do the rest of the configuration if we're building from source
        if not self.cfg['precompiled_binaries']:
            # installation prefix
            self.cfg.update('configopts', "-prefix %s" % self.installdir)

            # compilers

            # compilers & MPI
            if self.toolchain.options.get('usempi', None):
                self.cfg.update('configopts', "-%s -%s" % (os.environ['CC_SEQ'], os.environ['F90_SEQ']))
                if 'MPI_INC_DIR' in os.environ:
                    self.cfg.update('configopts', "-mpp -mppbase %s" % os.environ['MPI_INC_DIR'])
                else:
                    raise EasyBuildError("$MPI_INC_DIR not defined")
            else:
                self.cfg.update('configopts', "-%s -%s" % (os.environ['CC'], os.environ['F90']))

            # BLAS/LAPACK
            if 'BLAS_LIB_DIR' in os.environ:
                self.cfg.update('configopts', "-blas -blaspath %s" % os.environ['BLAS_LIB_DIR'])
            else:
                raise EasyBuildError("$BLAS_LIB_DIR not defined")

            if 'LAPACK_LIB_DIR' in os.environ:
                self.cfg.update('configopts', "-lapack -lapackpath %s" % os.environ['LAPACK_LIB_DIR'])
            else:
                raise EasyBuildError("$LAPACK_LIB_DIR not defined")

            # 32 vs 64 bit
            if self.toolchain.options.get('32bit', None):
                self.cfg.update('configopts', '-i4')
            else:
                self.cfg.update('configopts', '-i8')

            run_shell_cmd("./configure -batch %s" % self.cfg['configopts'])

            cfgfile = os.path.join(self.cfg['start_dir'], 'CONFIG')
            cfgtxt = read_file(cfgfile)

            # determine original LAUNCHER value
            launcher_regex = re.compile('^LAUNCHER=(.*)$', re.M)
            res = launcher_regex.search(cfgtxt)
            if res:
                self.orig_launcher = res.group(1)
                self.log.debug("Found original value for LAUNCHER: %s", self.orig_launcher)
            else:
                raise EasyBuildError("Failed to determine LAUNCHER value")

            # determine full installation prefix
            prefix_regex = re.compile('^PREFIX=(.*)$', re.M)
            res = prefix_regex.search(cfgtxt)
            if res:
                self.full_prefix = res.group(1)
                self.log.debug("Found full installation prefix: %s", self.full_prefix)
            else:
                raise EasyBuildError("Failed to determine full installation prefix")

            # determine MPI launcher command that can be used during build/test
            # obtain command with specific number of cores (required by mpi_cmd_for), then replace that number with '%n'
            launcher = self.toolchain.mpi_cmd_for('%x', self.cfg.parallel)
            launcher = launcher.replace(f' {self.cfg.parallel}', ' %n')

            # patch CONFIG file to change LAUNCHER definition, in order to avoid having to start mpd
            apply_regex_substitutions(cfgfile, [(r"^(LAUNCHER\s*=\s*).*$", r"\1 %s" % launcher)])

            # reread CONFIG and log contents
            cfgtxt = read_file(cfgfile)
            self.log.info("Contents of CONFIG file:\n%s", cfgtxt)

    def build_step(self):
        """Custom build procedure for Molpro, unless it is a binary install."""
        if not self.cfg['precompiled_binaries']:
            super(EB_Molpro, self).build_step()

    def test_step(self):
        """
        Custom test procedure for Molpro.
        Run 'make quicktest, make test', but only for source install and if license is available.
        """

        # Only bother to check if the licence token is available
        if os.path.isfile(self.license_token) and not self.cfg['precompiled_binaries']:

            # check 'main routes' only
            run_shell_cmd("make quicktest")

            if build_option('mpi_tests'):
                # extensive test
                run_shell_cmd(f"make MOLPRO_OPTIONS='-n{self.cfg.parallel}' test")
            else:
                self.log.info("Skipping extensive testing of Molpro since MPI testing is disabled")

    def install_step(self):
        """
        Custom install procedure for Molpro.
        For source install:
        * put license token in place in $installdir/.token
        * run 'make tuning'
        * install with 'make install'
        For binary install:
        * run interactive installer
        """

        if self.cfg['precompiled_binaries']:
            """Build by running the command with the inputfiles"""

            change_dir(self.cfg['start_dir'])

            for src in self.src:
                if LooseVersion(self.version) >= LooseVersion('2015'):
                    # install dir must be non-existent
                    shutil.rmtree(self.installdir)
                    cmd = "./{0} -batch -prefix {1}".format(src['name'], self.installdir)
                else:
                    cmd = "./{0} -batch -instbin {1}/bin -instlib {1}/lib".format(src['name'], self.installdir)

                bindir = os.path.join(self.installdir, 'bin')
                libdir = os.path.join(self.installdir, 'lib')

                qa = [
                    (r"Please give your username for accessing molpro\n", ''),
                    (r"Please give your password for accessing molpro\n", ''),
                    (r"Enter installation directory for executable files \[.*\]\n", bindir),
                    (r"Enter installation directory for library files \[.*\]\n", libdir),
                    (r"directory .* does not exist, try to create [Y]/n\n", ''),
                ]
                run_shell_cmd(cmd, qa_patterns=qa)
        else:
            if os.path.isfile(self.license_token):
                run_shell_cmd("make tuning")

            super(EB_Molpro, self).install_step()

            # put original LAUNCHER definition back in place in bin/molpro that got installed,
            # since the value used during installation point to temporary files
            molpro_path = os.path.join(self.full_prefix, 'bin', 'molpro')
            apply_regex_substitutions(molpro_path, [(r"^(LAUNCHER\s*=\s*).*$", r"\1 %s" % self.orig_launcher)])

        if self.cleanup_token_symlink:
            try:
                os.remove(self.license_token)
                self.log.debug("Symlink to license token %s removed", self.license_token)
            except OSError as err:
                raise EasyBuildError("Failed to remove %s: %s", self.license_token, err)

    def sanity_check_step(self):
        """Custom sanity check for Molpro."""
        prefix_subdir = os.path.basename(self.full_prefix)
        if not prefix_subdir:
            # we need to guess the installation prefix whenever the configure step is skipped
            # there are two possibles installation types:
            #   - A: installation located at the top level of self.installdir
            #   - B: installation located inside a subdirectory with a name specific to the
            #        installation type and platform (e.g. molpros_2012_1_Linux_x86_64_i8)
            path_to_bin = glob.glob(os.path.join(self.installdir, 'molpro*', 'bin'))
            if len(path_to_bin) > 0:
                prefix_subdir = os.path.relpath(os.path.dirname(path_to_bin[0]), self.installdir)

        files_to_check = ['bin/molpro']
        dirs_to_check = []
        if LooseVersion(self.version) >= LooseVersion('2015') or not self.cfg['precompiled_binaries']:
            files_to_check.extend(['bin/molpro.exe'])
            dirs_to_check.extend(['utilities'])
            if LooseVersion(self.version) <= LooseVersion('2021'):
                dirs_to_check.extend(['doc', 'examples'])
        custom_paths = {
            'files': [os.path.join(prefix_subdir, x) for x in files_to_check],
            'dirs': [os.path.join(prefix_subdir, x) for x in dirs_to_check],
        }
        super(EB_Molpro, self).sanity_check_step(custom_paths=custom_paths)
