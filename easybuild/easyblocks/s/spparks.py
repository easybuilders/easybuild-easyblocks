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
EasyBuild support for spparks, implemented as an easyblock

@author: Caspar van Leeuwen (SURF)
@author: Monica Rotulo (SURF)
"""
import os
import glob

from easybuild.easyblocks.generic.makecp import MakeCp
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.filetools import apply_regex_substitutions, change_dir, copy_file, symlink
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_cmd

DEFAULT_BUILD_CMD = 'make'
DEFAULT_TEST_CMD = 'make'


class EB_spparks(MakeCp):
    """Support for building/installing spparks."""

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to EB_spparks."""
        extra_vars = MakeCp.extra_options(extra_vars)
        extra_vars.update({
            'build_cmd': [DEFAULT_BUILD_CMD, "Build command to use", CUSTOM],
            'test_cmd': [DEFAULT_TEST_CMD, "Test command to use ('runtest' value is appended)", CUSTOM],
        })
        return extra_vars

    def configure_step(self):
        """Configure spparks build: locate the template makefile and patch it based on flags and deps from eb."""

        self.spparks_srcdir = os.path.join(self.cfg['start_dir'], 'src')

        # check if toolchain options exist. If so, set variable so it may be used in substitution in Makefile later on
        ccflags = ''
        if self.toolchain.options.get('optarch', False):
            ccflags += ' %s' % self.toolchain.get_flag('optarch')
        cstd = self.toolchain.options.get('cstd', None)
        if cstd:
            ccflags += ' %s' % self.toolchain.get_flag('cstd')

        if self.toolchain.options.get('pic', False):
            pic = '%s' % self.toolchain.get_flag('pic')
        else:
            pic = ''

        spk_inc = ''
        if self.toolchain.options.get('usempi', False):
            cxx = os.environ['MPICXX']
            # It's undocumented what this does, but the example makefiles seem to always contain it for MPI-based builds
            spk_inc += ' -DSPPARKS_UNORDERED_MAP'
        else:
            cxx = os.environ['CXX']

        # Build with gzip support?
        gzip_root = get_software_root('gzip')
        if gzip_root:
            spk_inc += ' -DSPPARKS_GZIP'

        # Build with jpeg support?
        jpeg_root = get_software_root('libjpeg-turbo')
        if jpeg_root:
            jpeg_lib = '-ljpeg'
            spk_inc += ' -DSPPARKS_JPEG'
        else:
            jpeg_lib = ''

        # Build with stitch support?
        stitch_root = get_software_root('stitch')
        if stitch_root:
            self.add_package = 'stitch'
            spk_inc += ' -DSTITCH_PARALLEL -DLOG_STITCH'

        regex_subs_spparks = [
            (r"^(CC\s*=\s*).*$", r"\1%s" % cxx),
            (r"^(LINK\s*=\s*).*$", r"\1%s" % cxx),
            (r"^(CCFLAGS\s*=\s*).*$", r"\1%s" % ccflags),
            (r"^(SHFLAGS\s*=\s*).*$", r"\1%s" % pic),
            (r"^(LINKFLAGS\s*=\s*).*$", r"\1%s" % os.environ['LDFLAGS']),
            (r"^(JPG_LIB\s*=\s*).*$", r"\1%s" % jpeg_lib),
            (r"^(SPK_INC\s*=\s*).*$", r"\1%s" % spk_inc),
        ]

        makefile_include_dir = os.path.join(self.spparks_srcdir, 'MAKE')
        # Parallel build?
        if self.toolchain.options.get('usempi', False):
            self.machine = 'mpi'
            # modify makefile for spparks, using the *.mpi makefile as starting point
            makefile_spparks = os.path.join(makefile_include_dir, 'Makefile.%s' % self.machine)
        else:
            self.machine = 'serial'
            # modify the serial makefile. We don't make a copy, since the Makefile has special behaviour
            # for the target 'serial', so we can't change the target name
            makefile_spparks = os.path.join(makefile_include_dir, 'Makefile.%s' % self.machine)

            # for the STUBS mpi library that spparks builds
            makefile_stubs = os.path.join(self.spparks_srcdir, 'STUBS', 'Makefile')
            ccflags_stubs = '%s %s' % (ccflags, pic)
            regex_subs_stubs = [
                (r"^(CC\s*=\s*).*$", r"\1%s" % cxx),
                (r"^(CCFLAGS\s*=\s*).*$", r"\1%s" % ccflags_stubs),
            ]
            apply_regex_substitutions(makefile_stubs, regex_subs_stubs)

        apply_regex_substitutions(makefile_spparks, regex_subs_spparks)

    def build_step(self, verbose=False, path=None):
        """
        Start the actual build
        - typical: make -j X
        """

        # Change dir to where the Makefile is
        change_dir(self.spparks_srcdir)

        paracmd = ''
        if self.cfg['parallel']:
            paracmd = "-j %s" % self.cfg['parallel']

        # Build targets
        targets = ['yes-%s' % self.add_package, self.machine]

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

    def test_step(self):
        """
        Test the compilation
        - typically: 'mpirun -np 2 spk_mpi -echo screen < ../examples/potts/in.potts'
        or 'spk_serial -echo screen < ../examples/potts/in.potts'
        """
        self.log.info("Running test step in directory %s" % os.getcwd())
        test_cmd = self.cfg.get('test_cmd')
        (out, _) = run_cmd(test_cmd, log_all=True, simple=False)

        return out

    def _copy_files_and_create_symlink(self, src, target, link_path=None):
        """
        Custom helper function to copy a source file to a destination directory and create a symbolic link if specified.

        This custom function is necessary due to the specific requirements of the SPPARKS installation process,
        which involves conditional renaming and linking of binaries and libraries based on the build configuration
        (e.g., MPI vs. serial). These requirements are not adequately met by the generic 'files_to_copy' mechanism provided by MakeCp,
        necessitating a more tailored approach to ensure correct installation structure and usability.

        - src: Source file path
        - target: Destination directory path
        - link_path: (Optional) Path of the symbolic link to create. If None, no symlink is created.
        """

        if not os.path.exists(target):
            copy_file(src, target)
            self.log.debug(f"Copied: {src} to {target}")
        else:
            self.log.debug(f"Skipped copying {src}, target already exists.")

        if link_path:
            if not os.path.islink(link_path) and not os.path.exists(link_path):
                symlink(target, link_path)
                self.log.debug(f"Created symlink: {link_path} -> {target}")
            else:
                self.log.debug(f"Skipped creating symlink for {src}, already exists.")

    def install_step(self):
        """Install by copying files and creating group library file."""

        super(EB_spparks, self).install_step()

        self.log.debug("Installing spparks by copying files")

        binaries = ['spk']
        headers = list(glob.glob(os.path.join(self.spparks_srcdir, '*.h')))

        self.log.debug("headers: %s" % headers)

        for binary in binaries:
            binary_name = '%s_%s' % (binary, self.machine)
            src = os.path.join(self.spparks_srcdir, binary_name)
            target = os.path.join(self.installdir, 'bin', binary_name)
            link = os.path.join(self.installdir, 'bin', binary)
            # copy files and create link spk => spk.<self.machine>
            self._copy_files_and_create_symlink(src, target, link)

        for header in headers:
            target = os.path.join(self.installdir, 'include', os.path.basename(header))
            self._copy_files_and_create_symlink(header, target)
