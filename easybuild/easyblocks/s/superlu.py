##
# Copyright 2009-2025 Ghent University, University of Luxembourg
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
EasyBuild support for building and installing the SuperLU library, implemented as an easyblock

@author: Xavier Besseron (University of Luxembourg)
@author: J. Sassmannshausen (ICL/UK)
"""

import os
from easybuild.tools import LooseVersion

from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import get_software_root, get_software_version, get_software_libdir


class EB_SuperLU(CMakeMake):
    """
    Support for building the SuperLU library
    """

    @staticmethod
    def extra_options():
        extra_vars = CMakeMake.extra_options()
        extra_vars['build_shared_libs'][0] = False
        extra_vars['separate_build_dir'][0] = True
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Constructor for SuperLU easyblock."""

        super(EB_SuperLU, self).__init__(*args, **kwargs)

        # if self.lib_ext is not set by CMakeMake, fall back to .a (static libraries by default)
        self.lib_ext = self.lib_ext or 'a'

    def configure_step(self):
        """
        Set the CMake options for SuperLU
        """
        # Make sure not to build the slow BLAS library included in the package
        # At least for version 5.3.0 the name has changed:
        superlu_version = self.version
        if LooseVersion(superlu_version) >= LooseVersion('5.3'):
            self.cfg.update('configopts', '-Denable_internal_blaslib=OFF')
        else:
            self.cfg.update('configopts', '-Denable_blaslib=OFF')

        # Set the BLAS library to use
        # For this, use the BLA_VENDOR option from the FindBLAS module of CMake
        # Check for all possible values at https://cmake.org/cmake/help/latest/module/FindBLAS.html
        toolchain_blas_list = self.toolchain.definition().get('BLAS', None)
        if toolchain_blas_list is None:
            # This toolchain has no BLAS library
            raise EasyBuildError("No BLAS library found in the toolchain")

        toolchain_blas = toolchain_blas_list[0]
        cmake_version = get_software_version('cmake')
        if toolchain_blas == 'imkl':
            imkl_version = get_software_version('imkl')
            if LooseVersion(imkl_version) >= LooseVersion('10'):
                # 'Intel10_64lp' -> For Intel mkl v10 64 bit,lp thread model, lp64 model
                # It should work for Intel MKL 10 and above, as long as the library names stay the same
                # SuperLU requires thread, 'Intel10_64lp_seq' will not work!
                self.cfg.update('configopts', '-DBLA_VENDOR="Intel10_64lp"')

            else:
                # 'Intel' -> For older versions of mkl 32 and 64 bit
                self.cfg.update('configopts', '-DBLA_VENDOR="Intel"')

        elif toolchain_blas in ['ACML', 'ATLAS']:
            self.cfg.update('configopts', '-DBLA_VENDOR="%s"' % toolchain_blas)

        elif toolchain_blas == 'OpenBLAS':
            if LooseVersion(cmake_version) >= LooseVersion('3.6'):
                self.cfg.update('configopts', '-DBLA_VENDOR="%s"' % toolchain_blas)
            else:
                # Unfortunately, OpenBLAS is not recognized by FindBLAS from CMake,
                # we have to specify the OpenBLAS library manually
                openblas_lib = os.path.join(get_software_root('OpenBLAS'), get_software_libdir('OpenBLAS'),
                                            "libopenblas.a")
                self.cfg.update('configopts', '-DBLAS_LIBRARIES="%s;pthread"' % openblas_lib)

        elif toolchain_blas == 'FlexiBLAS':
            if LooseVersion(cmake_version) >= LooseVersion('3.19'):
                self.cfg.update('configopts', '-DBLA_VENDOR="%s"' % toolchain_blas)
            else:
                # Unfortunately, FlexiBLAS is not recognized by FindBLAS from CMake,
                # we have to specify the FlexiBLAS library manually
                flexiblas_lib = os.path.join(get_software_root('FlexiBLAS'), get_software_libdir('FlexiBLAS'),
                                             "libflexiblas.so")
                self.cfg.update('configopts', '-DBLAS_LIBRARIES="%s;pthread"' % flexiblas_lib)

        else:
            # This BLAS library is not supported yet
            raise EasyBuildError("BLAS library '%s' is not supported yet", toolchain_blas)

        super(EB_SuperLU, self).configure_step()

    def test_step(self):
        """
        Run the testsuite of SuperLU
        """
        if self.cfg['runtest'] is None:
            self.cfg['runtest'] = 'test'
        super(EB_SuperLU, self).test_step()

    def install_step(self):
        """
        Custom install procedure for SuperLU
        """
        super(EB_SuperLU, self).install_step()

        libbits = 'lib'
        if not os.path.exists(os.path.join(self.installdir, libbits)):
            libbits = 'lib64'

        if not os.path.exists(os.path.join(self.installdir, libbits)):
            raise EasyBuildError("No lib or lib64 subdirectory exist in %s", self.installdir)

        libbits_path = os.path.join(self.installdir, libbits)
        expected_libpath = os.path.join(libbits_path, 'libsuperlu.%s' % self.lib_ext)
        actual_libpath = os.path.join(libbits_path, 'libsuperlu_%s.%s' % (self.cfg['version'], self.lib_ext))

        if not os.path.exists(expected_libpath):
            try:
                os.symlink(actual_libpath, expected_libpath)
            except OSError as err:
                raise EasyBuildError("Failed to create symlink '%s' -> '%s: %s", expected_libpath, actual_libpath, err)

    def sanity_check_step(self):
        """
        Check for main library files for SuperLU
        """
        custom_paths = {
            'files': ["include/supermatrix.h", os.path.join('lib', 'libsuperlu.%s' % self.lib_ext)],
            'dirs': [],
        }
        super(EB_SuperLU, self).sanity_check_step(custom_paths=custom_paths)
