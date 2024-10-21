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
EasyBuild support for building and installing HEALPix, implemented as an easyblock

@author: Kenneth Hoste (HPC-UGent)
@author: Josef Dvoracek (Institute of Physics, Czech Academy of Sciences)
"""
import os
from easybuild.tools import LooseVersion

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
            'gcc_target': ['generic_gcc', "Target to use when using a GCC-based compiler toolchain", CUSTOM],
        }

        return ConfigureMake.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Initialisation of custom class variables for HEALPix."""
        super(EB_HEALPix, self).__init__(*args, **kwargs)

        self.build_in_installdir = True

        # target:
        #   1: basic_gcc
        #   2: generic_gcc
        #   3: linux_icc
        #   4: optimized_gcc
        #   5: osx
        #   6: osx_icc
        self.target_string = None

        comp_fam = self.toolchain.comp_family()
        if comp_fam == toolchain.INTELCOMP:  # @UndefinedVariable
            self.target_string = 'linux_icc'
        elif comp_fam in [toolchain.DUMMY, toolchain.SYSTEM, toolchain.GCC]:  # @UndefinedVariable

            self.target_string = self.cfg['gcc_target']

            if self.target_string not in ['basic_gcc', 'generic_gcc', 'optimized_gcc']:
                raise EasyBuildError("Unknown GCC target specified: %s", self.target_string)
        else:
            raise EasyBuildError("Don't know how which C++ configuration to use for toolchain family '%s'", comp_fam)

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

        cmd = "./configure -L"
        qa = {
            r"Should I attempt to create these directories (Y\|n)?": 'Y',
            "full name of cfitsio library (libcfitsio.a):": '',
            r"Do you want this modification to be done (y\|N)?": 'y',
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
            r"Available configurations for C\+\+ compilation are:[\s\n\S]*" +
            r"(?P<nr>[0-9]+): %s[\s\n\S]*Choose one number:" % self.target_string: '%(nr)s',
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
        paths = {
            'CPATH': 'include',
            'LIBRARY_PATH': 'lib',
            'PATH': 'bin',
        }
        for key in sorted(paths):
            txt += self.module_generator.prepend_paths(key, os.path.join('src', 'cxx', self.target_string, paths[key]))

        return txt

    def sanity_check_step(self):
        """Custom sanity check for HEALPix."""
        binaries = [os.path.join('bin', x) for x in ['alteralm', 'anafast', 'hotspot', 'map2gif', 'median_filter',
                                                     'plmgen', 'sky_ng_sim', 'sky_ng_sim_bin', 'smoothing',
                                                     'synfast', 'ud_grade']]
        libraries = [os.path.join('lib', 'lib%s.a' % x) for x in ['chealpix', 'gif', 'healpix', 'hpxgif']]

        target_subdirs = ['bin', 'lib']
        if LooseVersion(self.version) >= LooseVersion('3'):
            # 'include' subdir is only there for recent HEALPix versions
            target_subdirs.append('include')

        custom_paths = {
            'files': binaries + libraries + [os.path.join('lib', 'libchealpix.%s' % get_shared_lib_ext())],
            'dirs': ['include'] + [os.path.join('src', 'cxx', self.target_string, x) for x in target_subdirs],
        }

        custom_commands = []
        if LooseVersion(self.version) >= LooseVersion('3'):
            custom_commands.extend([
                "cd %s && make test &> build/testresults.txt" % self.installdir,
                'test $(grep -c "test completed" %s/build/testresults.txt) -eq 4' % self.installdir,
                'test $(grep -c "normal completion" %s/build/testresults.txt) -eq 10' % self.installdir,
            ])

        super(EB_HEALPix, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
