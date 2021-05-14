##
# Copyright 2021-2021 Ghent University
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
EasyBuild support for building and installing FlexiBLAS, implemented as an easyblock

author: Kenneth Hoste (HPC-UGent)
"""
import os

from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.environment import setvar
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import get_shared_lib_ext


class EB_FlexiBLAS(CMakeMake):
    """Support for building/installing FlexiBLAS."""

    @staticmethod
    def extra_options():
        extra_vars = CMakeMake.extra_options()
        extra_vars.update({
            'blas_auto_detect': [False, "Let FlexiBLAS autodetect the BLAS libraries during configuration", CUSTOM],
            'enable_lapack': [True, "Enable LAPACK support, also includes the wrappers around LAPACK", CUSTOM],
            'flexiblas_default': [None, "Default BLAS lib to set at compile time. If not defined, " +
                                  "the first BLAS lib in the list of dependencies is set as default", CUSTOM],
        })
        extra_vars['separate_build_dir'][0] = True
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Easyblock constructor."""
        super(EB_FlexiBLAS, self).__init__(*args, **kwargs)

        build_dep_names = set(dep['name'] for dep in self.cfg.dependencies(build_only=True))
        dep_names = [dep['name'] for dep in self.cfg.dependencies()]
        self.blas_libs = [x for x in dep_names if x not in build_dep_names]

        self.obj_builddir = os.path.join(self.builddir, 'easybuild_obj')

    def configure_step(self):
        """Custom configuration for FlexiBLAS, based on which BLAS libraries are included as dependencies."""

        configopts = {
            'BLAS_AUTO_DETECT': ('OFF', 'ON')[bool(self.cfg['blas_auto_detect'])],
            'LAPACK': ('OFF', 'ON')[bool(self.cfg['enable_lapack'])],
            'FLEXIBLAS_DEFAULT': self.cfg['flexiblas_default'] or self.blas_libs[0],
        }

        supported_blas_libs = ['BLIS', 'NETLIB', 'OpenBLAS']

        # make sure that default backend is a supported library
        flexiblas_default = configopts['FLEXIBLAS_DEFAULT']
        if flexiblas_default not in supported_blas_libs:
            raise EasyBuildError("%s not in list of supported BLAS libs %s", flexiblas_default, supported_blas_libs)

        # make sure that all backends are supported libraries
        unsupported_libs = [x for x in self.blas_libs if x not in supported_blas_libs]
        if unsupported_libs:
            raise EasyBuildError("One or more unsupported libraries used: %s", ', '.join(unsupported_libs))

        # list of BLAS libraries to use is specified via -DEXTRA=...
        configopts['EXTRA'] = ';'.join(self.blas_libs)

        # for each library, we have to specify how to link to it via -DXXX_LIBRARY;
        # see https://github.com/mpimd-csc/flexiblas#setup-with-custom-blas-and-lapack-implementations
        for blas_lib in self.blas_libs:
            key = '%s_LIBRARY' % blas_lib
            configopts[key] = blas_lib.lower()

        # only add configure options to configopts easyconfig parameter if they're not defined yet,
        # to allow easyconfig to override specifies settings
        for key, value in sorted(configopts.items()):
            opt = '-D%s=' % key
            if key not in self.cfg['configopts']:
                self.cfg.update('configopts', opt + "'%s'" % value)

        # specify compiler commands with absolute paths, to ensure that RPATH wrapper scripts are used
        if build_option('rpath'):
            self.cfg['abs_path_compilers'] = True

        super(EB_FlexiBLAS, self).configure_step(builddir=self.obj_builddir)

    def test_step(self):
        """Run tests using each of the backends."""

        if build_option('rpath'):
            # inject build location of libflexiblas.so.3 to $LD_LIBRARY_PATH
            # (which is used as a fallback to find libraries not found via the locations listed in the RPATH section),
            # to ensure that test binaries can find the FlexiBLAS library
            ld_library_path = ':'.join([
                os.path.join(self.obj_builddir, 'lib'),
                os.path.join(self.obj_builddir, 'lib64'),
                '$LD_LIBRARY_PATH'
            ])
            self.cfg['pretestopts'] = ('export LD_LIBRARY_PATH="%s" && ' % ld_library_path) + self.cfg['pretestopts']

        # Show verbose output if a test fails
        setvar('CTEST_OUTPUT_ON_FAILURE', 'True')

        # run tests with default backend (NETLIB)
        test_cmd = ' '.join([
            self.cfg['pretestopts'],
            "make test",
            self.cfg['testopts'],
        ])
        run_cmd(test_cmd)

    def sanity_check_step(self):
        """Custom sanity check for FlexiBLAS."""

        shlib_ext = get_shared_lib_ext()

        libs = []

        # libraries in lib/
        top_libs = ['libflexiblas%s.%s' % (x, shlib_ext) for x in ('', '_api', '_mgmt')]
        libs.extend(os.path.join('lib', lf) for lf in top_libs)

        # libraries in lib/flexiblas/
        lower_lib_names = self.blas_libs + ['fallback_lapack', 'hook_dummy', 'hook_profile']
        lower_libs = ['libflexiblas_%s.%s' % (x.lower(), shlib_ext) for x in lower_lib_names]
        libs.extend(os.path.join('lib', 'flexiblas', lf) for lf in lower_libs)

        custom_paths = {
            'files': [os.path.join('bin', 'flexiblas'), os.path.join('etc', 'flexiblasrc')] + libs,
            'dirs': [os.path.join('etc', 'flexiblasrc.d'), os.path.join('share', 'man')],
        }

        custom_commands = [
            "flexiblas --help",
            "flexiblas list",
        ]

        # make sure that each BLAS library is supported by FlexiBLAS by checking output of 'flexiblas list'
        for blas_lib in self.blas_libs:
            custom_commands.append("flexiblas list | grep %s" % blas_lib.upper())

        super(EB_FlexiBLAS, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
