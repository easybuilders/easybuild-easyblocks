##
# Copyright 2009-2019 Ghent University
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
EasyBuild support for building and installing HEALPix, implemented as an easyblock

@author: Kenneth Hoste (HPC-UGent)
@author: Josef Dvoracek (Institute of Physics, Czech Academy of Sciences)
"""
import os

import easybuild.tools.toolchain as toolchain
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_cmd_qa
from easybuild.tools.systemtools import get_shared_lib_ext


class EB_HEALPix(ConfigureMake):
    """Support for building/installing HEALPix."""

    @staticmethod
    def extra_options():
        """There 3 variants of GCC build"""
        extra_vars = {
            'gcc_target': ['generic_gcc', "Use generic_gcc target", CUSTOM],
        }

        return ConfigureMake.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Initialisation of custom class variables for HEALPix."""
        super(EB_HEALPix, self).__init__(*args, **kwargs)

        self.build_in_installdir = True
        self.target_string = None

    def extract_step(self):
        """Extract sources."""
        # strip off 'Healpix_<version>' part to avoid having everything in a subdirectory
        self.cfg['unpack_options'] = "--strip-components=1"
        super(EB_HEALPix, self).extract_step()

    def configure_step(self):
        """Custom configuration procedure for HEALPix."""

        cfitsio = get_software_root('CFITSIO')
        if not cfitsio:
            raise EasyBuildError("Failed to determine root for CFITSIO, module not loaded?")

        # target:
        #   1: basic_gcc
        #   2: generic_gcc
        #   3: linux_icc
        #   4: optimized_gcc
        #   5: osx
        #   6: osx_icc

        self.comp_fam = self.toolchain.comp_family()
        if self.comp_fam == toolchain.INTELCOMP:  # @UndefinedVariable
            cxx_config = '3'  # linux_icc
            self.target_string = 'linux_icc'
        elif self.comp_fam == toolchain.GCC:  # @UndefinedVariable
            if self.cfg['gcc_target'] == 'basic_gcc':
                cxx_config = '1'
                self.target_string = 'basic_gcc'
            elif self.cfg['gcc_target'] == 'generic_gcc':
                cxx_config = '2'
                self.target_string = 'generic_gcc'
            elif self.cfg['gcc_target'] == 'optimized_gcc':
                cxx_config = '4'
                self.target_string = 'optimized_gcc'
            else:
                # by default let's go with generic_gcc:
                cxx_config = '2'
                self.target_string = 'generic_gcc'
        else:
            raise EasyBuildError("Don't know how which C++ configuration for the used toolchain.")

        cmd = "./configure -L"
        qa = {
            "Should I attempt to create these directories (Y\|n)?": 'Y',
            "full name of cfitsio library (libcfitsio.a):": '',
            "Do you want this modification to be done (y\|N)?": 'y',
            "enter suffix for directories ():": '',
            # configure for C (2), Fortran (3), C++ (4), then exit (0)
            "Enter your choice (configuration of packages can be done in any order):": ['2', '3', '4', '0'],
        }
        std_qa = {
            r"C compiler you want to use \(\S*\):": os.environ['CC'],
            r"enter name of your F90 compiler \(\S*\):": os.environ['F90'],
            r"enter name of your C compiler \(\S*\):": os.environ['CC'],
            r"options for C compiler \([^)]*\):": os.environ['CFLAGS'],
            r"enter compilation/optimisation flags for C compiler \([^)]*\):": os.environ['CFLAGS'],
            r"compilation flags for %s compiler \([^:]*\):" % os.environ['F90']: '',
            r"enter optimisation flags for %s compiler \([^)]*\):" % os.environ['F90']: os.environ['F90FLAGS'],
            r"location of cfitsio library \(\S*\):": os.path.join(cfitsio, 'lib'),
            r"cfitsio header fitsio.h \(\S*\):": os.path.join(cfitsio, 'include'),
            r"enter command for library archiving \([^)]*\):": '',
            r"archive creation \(and indexing\) command \([^)]*\):": '',
            r"A static library is produced by default. Do you also want a shared library.*": 'y',
            r"Available configurations for C\+\+ compilation are:[\s\n\S]*Choose one number:": cxx_config,
            r"PGPLOT.[\s\n]*Do you want to enable this option \?[\s\n]*\([^)]*\) \(y\|N\)": 'N',
            r"the parallel implementation[\s\n]*Enter choice.*": '1',
            r"do you want the HEALPix/C library to include CFITSIO-related functions \? \(Y\|n\):": 'Y',
            r"\(recommended if the Healpix-F90 library is to be linked to external codes\)  \(Y\|n\):": 'Y',  # PIC -> Y
            r"Do you rather want a shared/dynamic library.*": 'n',  # shared instead static? -> N
        }
        run_cmd_qa(cmd, qa, std_qa=std_qa, log_all=True, simple=True, log_ok=True)

    def build_step(self):
        """Custom build procedure for HEALPix."""
        # disable parallel build
        self.cfg['parallel'] = '1'
        self.log.debug("Disabled parallel build")
        super(EB_HEALPix, self).build_step()

    def install_step(self):
        """No dedicated install procedure for HEALPix."""
        pass

    def make_module_extra(self):
        """additional paths"""
        txt = super(EB_HEALPix, self).make_module_extra()
        txt += self.module_generator.prepend_paths('PATH', os.path.join('src/cxx', self.target_string, 'bin'))
        txt += self.module_generator.prepend_paths('LIBRARY_PATH', os.path.join('src/cxx', self.target_string, 'lib'))
        txt += self.module_generator.prepend_paths('CPATH', os.path.join('src/cxx', self.target_string, 'include'))
        return txt

    def sanity_check_step(self):
        """sanity checks"""
        custom_paths = {
            'files': [os.path.join('bin', x) for x in ['alteralm', 'anafast', 'hotspot', 'map2gif', 'median_filter',
                                                       'plmgen', 'sky_ng_sim', 'sky_ng_sim_bin', 'smoothing',
                                                       'synfast', 'ud_grade']] +
                     [os.path.join('lib', 'lib%s.a' % x) for x in ['chealpix', 'gif', 'healpix', 'hpxgif']] +
                     [os.path.join('lib', 'libchealpix.%s' % get_shared_lib_ext())],
            'dirs': [
                os.path.join(self.installdir, 'include'),
                os.path.join(self.installdir, 'src/cxx', self.target_string, 'bin'),
                os.path.join(self.installdir, 'src/cxx', self.target_string, 'lib'),
                os.path.join(self.installdir, 'src/cxx', self.target_string, 'include'),
            ],
        }
        super(EB_HEALPix, self).sanity_check_step(custom_paths=custom_paths)
