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
        self.internal_ntpoly = True
        self.env_suff = '_MT' if self.toolchain.options.get('openmp', None) else ''

    @staticmethod
    def extra_options():
        """Define custom easyconfig parameters for ELSI."""
        extra_vars = CMakeMake.extra_options()
        extra_vars.update({
            'build_internal_pexsi': [None, "Build internal PEXSI solver", CUSTOM],
        })
        extra_vars['separate_build_dir'][0] = True
        extra_vars['build_shared_libs'][0] = True
        return extra_vars

    def configure_step(self):
        """Custom configure procedure for ELSI."""
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
            inc_paths.append(os.path.join(elpa_root, 'include', '%s-%s' % (elpa_lib, get_software_version('ELPA')),
                                          'modules'))
            external_libs.extend([elpa_lib])
        else:
            self.log.info("No external ELPA specified as dependency, building internal ELPA.")

        pexsi = get_software_root('PEXSI')
        if pexsi:
            if self.cfg['build_internal_pexsi']:
                raise EasyBuildError("Both build_internal_pexsi and external PEXSI dependency found, "
                                     "only one can be set.")
            self.log.info("Using external PEXSI.")
            self.cfg.update('configopts', "-DUSE_EXTERNAL_PEXSI=ON")
            external_libs.append('pexsi')
        elif self.cfg['build_internal_pexsi'] is not False:
            self.log.info("No external PEXSI specified as dependency and internal PEXSI not explicitly disabled, "
                          "building internal PEXSI.")
            self.cfg['build_internal_pexsi'] = True
        else:
            self.log.info("No external PEXSI specified as dependency and internal PEXSI was explicitly disabled, "
                          "building ELSI without PEXSI.")

        if pexsi or self.cfg['build_internal_pexsi']:
            self.cfg.update('configopts', "-DENABLE_PEXSI=ON")

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

        ntpoly = get_software_root('NTPoly')
        if ntpoly:
            self.internal_ntpoly = False
            self.log.info("Using external NTPoly.")
            self.cfg.update('configopts', "-DUSE_EXTERNAL_NTPOLY=ON")
            external_libs.append('NTPoly')
        else:
            self.log.info("No external NTPoly specified as dependency, building internal NTPoly.")

        bsepack = get_software_root('bsepack')
        if bsepack:
            self.log.info("Using external BSEPACK.")
            self.cfg.update('configopts', "-DENABLE_BSEPACK=ON -DUSE_EXTERNAL_BSEPACK=ON")
            external_libs.extend(['bsepack', 'sseig'])

        if get_software_root('imkl') or get_software_root('ScaLAPACK'):
            external_libs.extend(re.findall(r'lib(.*?)\.a', os.environ['SCALAPACK%s_STATIC_LIBS' % self.env_suff]))
        else:
            raise EasyBuildError("Could not find ScaLAPACK library or interface.")

        external_libs.extend(re.findall(r'-l(.*?)\b', os.environ['LIBS']))

        self.cfg.update('configopts', "-DLIBS='%s'" % ';'.join(external_libs))
        self.cfg.update('configopts', "-DLIB_PATHS='%s'" % ';'.join(lib_paths))
        self.cfg.update('configopts', "-DINC_PATHS='%s'" % ';'.join(inc_paths))

        super(EB_ELSI, self).configure_step()

    def sanity_check_step(self):
        """Custom sanity check for ELSI."""

        libs = ['elsi', 'fortjson', 'MatrixSwitch', 'OMM']
        if self.internal_ntpoly:
            libs.append('NTPoly')
        modules = [lib.lower() for lib in libs if lib != 'OMM']
        modules.extend(['omm_ops', 'omm_params', 'omm_rand'])

        if self.cfg['build_internal_pexsi']:
            modules.append('elsi_pexsi')
            libs.extend(['pexsi', 'ptscotch', 'ptscotcherr', 'ptscotchparmetis',
                         'scotch', 'scotcherr', 'scotchmetis', 'superlu_dist'])

        if self.enable_sips:
            modules.append('elsi_sips')
            libs.append('sips')

        # follow self.lib_ext set by CMakeMake (based on build_shared_libs), fall back to .a (static libs by default)
        lib_ext = self.lib_ext or 'a'

        module_paths = [os.path.join('include', '%s.mod' % mod) for mod in modules]
        lib_paths = [os.path.join('lib', 'lib%s.%s' % (lib, lib_ext)) for lib in libs]

        custom_paths = {
            'files': module_paths + lib_paths,
            'dirs': [],
        }

        super(EB_ELSI, self).sanity_check_step(custom_paths=custom_paths)
