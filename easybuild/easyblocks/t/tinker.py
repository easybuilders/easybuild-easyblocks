##
# Copyright 2009-2025 Ghent University
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
EasyBuild support for building and installing TINKER, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
"""
import glob
import os
import tempfile

from easybuild.tools import LooseVersion

import easybuild.tools.toolchain as toolchain
from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import apply_regex_substitutions, change_dir, copy_dir, copy_file, mkdir
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.systemtools import DARWIN, LINUX, get_os_type


class EB_TINKER(EasyBlock):
    """Support for building/installing TINKER."""

    def __init__(self, *args, **kwargs):
        """Custom easyblock constructor for TINKER: initialise class variables."""
        super(EB_TINKER, self).__init__(*args, **kwargs)

        self.build_subdir = None
        self.build_in_installdir = True

        self.module_load_environment.LD_LIBRARY_PATH.append(os.path.join('tinker', 'source'))
        self.module_load_environment.PATH.append(os.path.join('tinker', 'bin'))

    def configure_step(self):
        """Custom configuration procedure for TINKER."""
        # make sure FFTW is available
        if get_software_root('FFTW') is None:
            raise EasyBuildError("FFTW dependency is not available.")

        os_dirs = {
            LINUX: 'linux',
            DARWIN: 'macosx',
        }
        os_type = get_os_type()
        os_dir = os_dirs.get(os_type)
        if os_dir is None:
            raise EasyBuildError("Failed to determine OS directory for %s (known: %s)", os_type, os_dirs)

        comp_dirs = {
            toolchain.INTELCOMP: 'intel',
            toolchain.GCC: 'gfortran',
        }
        comp_fam = self.toolchain.comp_family()
        comp_dir = comp_dirs.get(comp_fam)
        if comp_dir is None:
            raise EasyBuildError("Failed to determine compiler directory for %s (known: %s)", comp_fam, comp_dirs)

        self.build_subdir = os.path.join(os_dir, comp_dir)
        self.log.info("Using build scripts from %s subdirectory" % self.build_subdir)

        # patch 'link.make' script to use FFTW provided via EasyBuild
        link_make_fp = os.path.join(self.cfg['start_dir'], self.build_subdir, 'link.make')
        regex_subs = [(r"libfftw3_threads.a libfftw3.a", r"-L$EBROOTFFTW/lib -lfftw3_omp -lfftw3")]
        apply_regex_substitutions(link_make_fp, regex_subs)

        # patch *.make files to get rid of hardcoded -openmp flag,
        # which doesn't work anymore with recent Intel compilers
        if comp_fam == toolchain.INTELCOMP:
            make_fps = glob.glob(os.path.join(self.cfg['start_dir'], self.build_subdir, '*.make'))
            regex_subs = [(r'-openmp', r'-fopenmp')]
            for make_fp in make_fps:
                apply_regex_substitutions(make_fps, regex_subs)

    def build_step(self):
        """Custom build procedure for TINKER."""

        change_dir(os.path.join(self.cfg['start_dir'], 'source'))

        for make in ['compile', 'library', 'link']:
            run_shell_cmd(os.path.join(self.cfg['start_dir'], self.build_subdir, f'{make}.make'))

    def test_step(self):
        """Custom built-in test procedure for TINKER."""
        if self.cfg['runtest']:
            # copy tests, params and built binaries to temporary directory for testing
            tmpdir = tempfile.mkdtemp()
            testdir = os.path.join(tmpdir, 'test')

            mkdir(os.path.join(tmpdir, 'bin'))
            binaries = glob.glob(os.path.join(self.cfg['start_dir'], 'source', '*.x'))
            for binary in binaries:
                copy_file(binary, os.path.join(tmpdir, 'bin', os.path.basename(binary)[:-2]))
            copy_dir(os.path.join(self.cfg['start_dir'], 'test'), testdir)
            copy_dir(os.path.join(self.cfg['start_dir'], 'params'), os.path.join(tmpdir, 'params'))

            change_dir(testdir)

            # run all tests via the provided 'run' scripts
            tests = glob.glob(os.path.join(testdir, '*.run'))

            # gpcr takes too long (~1h)
            skip_tests = ['gpcr']
            if (LooseVersion(self.version) < LooseVersion('8.7.2')):
                # ifabp fails due to input issues (?)
                skip_tests.append('ifabp')
            if (LooseVersion(self.version) >= LooseVersion('8.7.2')):
                # salt and dialinine takes too long
                skip_tests.extend(['salt', 'dialanine'])

            tests = [t for t in tests if not any([t.endswith('%s.run' % x) for x in skip_tests])]

            for test in tests:
                run_shell_cmd(test)

    def install_step(self):
        """Custom install procedure for TINKER."""

        change_dir(os.path.join(self.cfg['start_dir'], 'source'))

        mkdir(os.path.join(self.cfg['start_dir'], 'bin'))
        run_shell_cmd(os.path.join(self.cfg['start_dir'], self.build_subdir, 'rename.make'))

    def sanity_check_step(self):
        """Custom sanity check for TINKER."""
        custom_paths = {
            'files': ['tinker/source/libtinker.a'],
            'dirs': ['tinker/bin'],
        }
        super(EB_TINKER, self).sanity_check_step(custom_paths=custom_paths)
