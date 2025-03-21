##
# Copyright 2013-2025 Ghent University
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
EasyBuild support for building and installing ESMF, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
@author: Damian Alvarez (Forschungszentrum Juelich GmbH)
@author: Maxime Boissonneault (Digital Research Alliance of Canada)
"""
import os
from easybuild.tools import LooseVersion

import easybuild.tools.environment as env
import easybuild.tools.toolchain as toolchain
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.systemtools import get_shared_lib_ext
from easybuild.framework.easyconfig import CUSTOM


class EB_ESMF(ConfigureMake):
    """Support for building/installing ESMF."""

    @staticmethod
    def extra_options():
        """Custom easyconfig parameters for ESMF"""
        extra_vars = {
            'disable_lapack': [False, 'Disable external LAPACK - True or False', CUSTOM]
        }
        return ConfigureMake.extra_options(extra_vars)

    def configure_step(self):
        """Custom configuration procedure for ESMF through environment variables."""

        env.setvar('ESMF_DIR', self.cfg['start_dir'])
        env.setvar('ESMF_INSTALL_PREFIX', self.installdir)
        env.setvar('ESMF_INSTALL_BINDIR', 'bin')
        env.setvar('ESMF_INSTALL_LIBDIR', 'lib')
        env.setvar('ESMF_INSTALL_MODDIR', 'mod')

        # specify compiler
        comp_family = self.toolchain.comp_family()
        if comp_family in [toolchain.GCC]:
            compiler = 'gfortran'
        else:
            compiler = comp_family.lower()
        env.setvar('ESMF_COMPILER', compiler)

        env.setvar('ESMF_F90COMPILEOPTS', os.getenv('F90FLAGS'))
        env.setvar('ESMF_CXXCOMPILEOPTS', os.getenv('CXXFLAGS'))

        # specify MPI communications library
        comm = None
        mpi_family = self.toolchain.mpi_family()
        if mpi_family in [toolchain.MPICH, toolchain.QLOGICMPI]:
            # MPICH family for MPICH v3.x, which is MPICH2 compatible
            comm = 'mpich2'
        else:
            comm = mpi_family.lower()
        env.setvar('ESMF_COMM', comm)

        # specify decent LAPACK lib
        if self.cfg['disable_lapack']:
            env.setvar('ESMF_LAPACK', 'OFF')
            # MOAB can't be built without LAPACK
            env.setvar('ESMF_MOAB', 'OFF')
        else:
            env.setvar('ESMF_LAPACK', 'user')
            ldflags = os.getenv('LDFLAGS')
            liblapack = os.getenv('LIBLAPACK_MT') or os.getenv('LIBLAPACK')
            if liblapack is None:
                msg = "$LIBLAPACK(_MT) not defined, no BLAS/LAPACK in %s toolchain?"
                raise EasyBuildError(msg, self.toolchain.name)
            else:
                env.setvar('ESMF_LAPACK_LIBS', ldflags + ' ' + liblapack)

        # specify netCDF
        netcdf = get_software_root('netCDF')
        if netcdf:
            if LooseVersion(self.version) >= LooseVersion('7.1.0'):
                env.setvar('ESMF_NETCDF', 'nc-config')
            else:
                env.setvar('ESMF_NETCDF', 'user')
                netcdf_libs = ['-L%s/lib' % netcdf, '-lnetcdf']

                # Fortran
                netcdff = get_software_root('netCDF-Fortran')
                if netcdff:
                    netcdf_libs = ["-L%s/lib" % netcdff] + netcdf_libs + ["-lnetcdff"]
                else:
                    netcdf_libs.append('-lnetcdff')

                # C++
                netcdfcxx = get_software_root('netCDF-C++')
                if netcdfcxx:
                    netcdf_libs = ["-L%s/lib" % netcdfcxx] + netcdf_libs + ["-lnetcdf_c++"]
                else:
                    netcdfcxx = get_software_root('netCDF-C++4')
                    if netcdfcxx:
                        netcdf_libs = ["-L%s/lib" % netcdfcxx] + netcdf_libs + ["-lnetcdf_c++4"]
                    else:
                        netcdf_libs.append('-lnetcdf_c++')
                env.setvar('ESMF_NETCDF_LIBS', ' '.join(netcdf_libs))

        # 'make info' provides useful debug info
        run_shell_cmd("make info")

    def install_step(self):
        # first, install the software
        super(EB_ESMF, self).install_step()

        python = get_software_version('Python')
        if python:
            # then, install the python bindings
            py_subdir = os.path.join(self.builddir, 'esmf-ESMF_%s' % '_'.join(self.version.split('.')),
                                     'src', 'addon', 'ESMPy')
            try:
                os.chdir(py_subdir)
            except OSError as err:
                raise EasyBuildError("Failed to move to: %s", err)

            cmd = "python setup.py build --ESMFMKFILE=%s/lib/esmf.mk " % self.installdir
            cmd += " && python setup.py install --prefix=%s" % self.installdir
            run_shell_cmd(cmd)

    def make_module_extra(self):
        """Set $ESMFMKFILE environment variable"""
        txt = super(EB_ESMF, self).make_module_extra()

        # set environment variable ESMFMKFILE
        # see section 9.9 in https://earthsystemmodeling.org/docs/release/latest/ESMF_usrdoc/node10.html
        esmf_mkfile_path = os.path.join(self.installdir, "lib", "esmf.mk")
        txt += self.module_generator.set_environment('ESMFMKFILE', esmf_mkfile_path)

        return txt

    def sanity_check_step(self):
        """Custom sanity check for ESMF."""

        if LooseVersion(self.version) < LooseVersion('8.1.0'):
            binaries = ['ESMF_Info', 'ESMF_InfoC', 'ESMF_Regrid', 'ESMF_RegridWeightGen',
                        'ESMF_Scrip2Unstruct', 'ESMF_WebServController']
        else:
            binaries = ['ESMF_PrintInfo', 'ESMF_PrintInfoC', 'ESMF_Regrid', 'ESMF_RegridWeightGen',
                        'ESMF_Scrip2Unstruct', 'ESMF_WebServController']

        libs = ['esmf.mk', 'libesmf.a', 'libesmf.%s' % get_shared_lib_ext()]
        custom_paths = {
            'files': [os.path.join('bin', x) for x in binaries] + [os.path.join('lib', x) for x in libs],
            'dirs': ['include', 'mod'],
        }

        custom_commands = []
        if get_software_root('Python'):
            custom_commands += ["python -s -c 'import ESMF'"]

        super(EB_ESMF, self).sanity_check_step(custom_commands=custom_commands, custom_paths=custom_paths)
