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
EasyBuild support for ELSI, implemented as an easyblock

@author: Miguel Dias Costa (National University of Singapore)
"""
import os
import re
from easybuild.easyblocks.generic.cmakemake import CMakeMake, setup_cmake_env
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import get_software_root, get_software_version


class EB_ELSI(CMakeMake):
    """Support for building ELSI."""

    def __init__(self, *args, **kwargs):
        """Initialize ELSI-specific variables."""
        super(EB_ELSI, self).__init__(*args, **kwargs)
        self.enable_sips = False
        self.env_suff = '_MT' if self.toolchain.options.get('openmp', None) else ''

    @staticmethod
    def extra_options():
        """Define custom easyconfig parameters for ELSI."""
        extra_vars = {
            'build_internal_pexsi': [False, "Build internal PEXSI solver", CUSTOM],
        }
        return CMakeMake.extra_options(extra_vars)

    def configure_step(self):
        """Custom configure procedure for ELSI."""

        self.cfg['separate_build_dir'] = True

        if self.cfg['runtest']:
            self.cfg.update('configopts', "-DENABLE_TESTS=ON")
            self.cfg.update('configopts', "-DENABLE_C_TESTS=ON")
            self.cfg['runtest'] = 'test'

        setup_cmake_env(self.toolchain)

        external_libs = []
        inc_paths = os.environ['CMAKE_INCLUDE_PATH'].split(':')
        lib_paths = os.environ['CMAKE_LIBRARY_PATH'].split(':')

        elpa_root = get_software_root('ELPA')
        if elpa_root:
            self.log.info("Using external ELPA.")
            self.cfg.update('configopts', "-DUSE_EXTERNAL_ELPA=ON")
            elpa_lib = 'elpa_openmp' if self.toolchain.options.get('openmp', None) else 'elpa'
            inc_paths.append('%s/include/%s-%s/modules' % (elpa_root, elpa_lib, get_software_version('ELPA')))
            external_libs.extend([elpa_lib])
        else:
            self.log.info("No external ELPA specified as dependency, building internal ELPA.")

        pexsi = get_software_root('PEXSI')
        if pexsi and self.cfg['build_internal_pexsi']:
            raise EasyBuildError("Both build_internal_pexsi and external PEXSI dependency found, only one can be set.")
        if pexsi or self.cfg['build_internal_pexsi']:
            self.log.info("Enabling PEXSI solver.")
            self.cfg.update('configopts', "-DENABLE_PEXSI=ON")
            if pexsi:
                self.log.info("Using external PEXSI.")
                self.cfg.update('configopts', "-DUSE_EXTERNAL_PEXSI=ON")
                external_libs.append('pexsi')
            else:
                self.log.info("No external PEXSI specified as dependency, building internal PEXSI.")

        slepc = get_software_root('SLEPc')
        if slepc:
            if self.cfg['build_internal_pexsi']:
                # ELSI's internal PEXSI also builds internal PT-SCOTCH and SuperLU_DIST
                raise EasyBuildError("Cannot use internal PEXSI with external SLEPc, due to conflicting dependencies.")
            self.enable_sips = True
            self.log.info("Enabling SLEPc-SIPs solver.")
            self.cfg.update('configopts', "-DENABLE_SIPS=ON")
            external_libs.extend(['slepc', 'petsc', 'HYPRE', 'umfpack', 'klu', 'cholmod', 'btf', 'ccolamd', 'colamd',
                                  'camd', 'amd', 'suitesparseconfig', 'metis', 'ptesmumps',
                                  'ptscotchparmetis', 'ptscotch', 'ptscotcherr', 'esmumps', 'scotch', 'scotcherr',
                                  'stdc++', 'dl'])
            if get_software_root('imkl') or get_software_root('FFTW'):
                external_libs.extend(re.findall(r'lib(.*?)\.a', os.environ['FFTW_STATIC_LIBS%s' % self.env_suff]))
            else:
                raise EasyBuildError("Could not find FFTW library or interface.")

        if get_software_root('imkl') or get_software_root('SCALAPACK'):
            external_libs.extend(re.findall(r'lib(.*?)\.a', os.environ['SCALAPACK%s_STATIC_LIBS' % self.env_suff]))
        else:
            raise EasyBuildError("Could not find SCALAPACK library or interface.")

        external_libs.extend(re.findall(r'-l(.*?)\b', os.environ['LIBS']))

        self.cfg.update('configopts', "-DLIBS='%s'" % ';'.join(external_libs))
        self.cfg.update('configopts', "-DLIB_PATHS='%s'" % ';'.join(lib_paths))
        self.cfg.update('configopts', "-DINC_PATHS='%s'" % ';'.join(inc_paths))

        super(EB_ELSI, self).configure_step()

    def sanity_check_step(self):
        """Custom sanity check for ELSI."""

        libs = ['elsi', 'fortjson', 'MatrixSwitch', 'NTPoly', 'OMM']
        modules = [lib.lower() for lib in libs if lib != 'OMM']
        modules.extend(['omm_ops', 'omm_params', 'omm_rand'])

        if self.cfg['build_internal_pexsi']:
            modules.append('elsi_pexsi')
            libs.extend(['pexsi', 'ptscotch', 'ptscotcherr', 'ptscotchparmetis',
                         'scotch', 'scotcherr', 'scotchmetis', 'superlu_dist'])

        if self.enable_sips:
            modules.append('elsi_sips')
            libs.append('sips')

        custom_paths = {
            'files': ['include/%s.mod' % mod for mod in modules] + ['lib/lib%s.a' % lib for lib in libs],
            'dirs': [],
        }

        super(EB_ELSI, self).sanity_check_step(custom_paths=custom_paths)
