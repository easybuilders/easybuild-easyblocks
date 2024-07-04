##
# Copyright 2013-2024 Ghent University
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
EasyBuild support for building and installing PSI, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
@author: Ward Poelmans (Ghent University)
"""

from easybuild.tools import LooseVersion
import glob
import os
import shutil
import tempfile

import easybuild.tools.environment as env
from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import BUILD
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_cmd


class EB_PSI(CMakeMake):
    """
    Support for building and installing PSI
    """

    def __init__(self, *args, **kwargs):
        """Initialize class variables custom to PSI."""
        super(EB_PSI, self).__init__(*args, **kwargs)

        self.psi_srcdir = None
        self.install_psi_objdir = None
        self.install_psi_srcdir = None

    @staticmethod
    def extra_options():
        """Extra easyconfig parameters specific to PSI."""
        extra_vars = CMakeMake.extra_options()
        extra_vars.update({
            # always include running PSI unit tests (takes about 2h or less)
            'runtest': ["tests TESTFLAGS='-u -q'", "Run tests included with PSI, without interruption.", BUILD],
        })
        # Doesn't work with out-of-source build
        extra_vars['separate_build_dir'][0] = False
        return extra_vars

    def configure_step(self):
        """
        Configure build outside of source directory.
        """
        try:
            objdir = os.path.join(self.builddir, 'obj')
            os.makedirs(objdir)
            os.chdir(objdir)
        except OSError as err:
            raise EasyBuildError("Failed to prepare for configuration of PSI build: %s", err)

        env.setvar('F77FLAGS', os.getenv('F90FLAGS'))

        # In order to create new plugins with PSI, it needs to know the location of the source
        # and the obj dir after install. These env vars give that information to the configure script.
        self.psi_srcdir = os.path.basename(self.cfg['start_dir'].rstrip(os.sep))
        self.install_psi_objdir = os.path.join(self.installdir, 'obj')
        self.install_psi_srcdir = os.path.join(self.installdir, self.psi_srcdir)
        env.setvar('PSI_OBJ_INSTALL_DIR', self.install_psi_objdir)
        env.setvar('PSI_SRC_INSTALL_DIR', self.install_psi_srcdir)

        # explicitely specify Python binary to use
        pythonroot = get_software_root('Python')
        if not pythonroot:
            raise EasyBuildError("Python module not loaded.")

        # pre 4.0b5, they were using autotools, on newer it's CMake
        if LooseVersion(self.version) <= LooseVersion("4.0b5") and self.name == "PSI":
            # Use EB Boost
            boostroot = get_software_root('Boost')
            if not boostroot:
                raise EasyBuildError("Boost module not loaded.")

            self.log.info("Using configure based build")
            env.setvar('PYTHON', os.path.join(pythonroot, 'bin', 'python'))
            env.setvar('USE_SYSTEM_BOOST', 'TRUE')

            if self.toolchain.options.get('usempi', None):
                # PSI doesn't require a Fortran compiler itself, but may require it to link to BLAS/LAPACK correctly
                # we should always specify the sequential Fortran compiler,
                # to avoid problems with -lmpi vs -lmpi_mt during linking
                fcompvar = 'F77_SEQ'
            else:
                fcompvar = 'F77'

            # update configure options
            # using multi-threaded BLAS/LAPACK is important for performance,
            # cfr. http://sirius.chem.vt.edu/psi4manual/latest/installfile.html#sec-install-iii
            opt_vars = [
                ('cc', 'CC'),
                ('cxx', 'CXX'),
                ('fc', fcompvar),
                ('libdirs', 'LDFLAGS'),
                ('blas', 'LIBBLAS_MT'),
                ('lapack', 'LIBLAPACK_MT'),
            ]
            for (opt, var) in opt_vars:
                self.cfg.update('configopts', "--with-%s='%s'" % (opt, os.getenv(var)))

            # -DMPICH_IGNORE_CXX_SEEK dances around problem with order of stdio.h and mpi.h headers
            # both define SEEK_SET, this makes the one for MPI be ignored
            self.cfg.update('configopts', "--with-opt='%s -DMPICH_IGNORE_CXX_SEEK'" % os.getenv('CFLAGS'))

            # specify location of Boost
            self.cfg.update('configopts', "--with-boost=%s" % boostroot)

            # enable support for plugins
            self.cfg.update('configopts', "--with-plugins")

            ConfigureMake.configure_step(self, cmd_prefix=self.cfg['start_dir'])
        else:
            self.log.info("Using CMake based build")
            self.cfg.update('configopts', ' -DPYTHON_EXECUTABLE=%s' % os.path.join(pythonroot, 'bin', 'python'))
            if self.name == 'PSI4' and LooseVersion(self.version) >= LooseVersion("1.2"):
                self.log.info("Remove the CMAKE_BUILD_TYPE test in PSI4 source and the downloaded dependencies!")
                self.log.info("Use PATCH_COMMAND in the corresponding CMakeLists.txt")
                self.cfg['build_type'] = 'EasyBuildRelease'

            if self.toolchain.options.get('usempi', None):
                self.cfg.update('configopts', " -DENABLE_MPI=ON")

            if get_software_root('imkl'):
                self.cfg.update('configopts', " -DENABLE_CSR=ON -DBLAS_TYPE=MKL")

            if self.name == 'PSI4':
                pcmsolverroot = get_software_root('PCMSolver')
                if pcmsolverroot:
                    if LooseVersion(self.version) >= LooseVersion("1.1"):
                        pcmsolver = 'PCMSolver'
                    else:
                        pcmsolver = 'PCMSOLVER'
                    self.cfg.update('configopts', " -DENABLE_%s=ON" % pcmsolver)
                    if LooseVersion(self.version) < LooseVersion("1.2"):
                        self.cfg.update('configopts', " -DPCMSOLVER_ROOT=%s" % pcmsolverroot)
                    else:
                        self.cfg.update('configopts', " -DCMAKE_INSIST_FIND_PACKAGE_PCMSolver=ON "
                                        "-DPCMSolver_DIR=%s/share/cmake/PCMSolver" % pcmsolverroot)

                chempsroot = get_software_root('CheMPS2')
                if chempsroot:
                    if LooseVersion(self.version) >= LooseVersion("1.1"):
                        chemps2 = 'CheMPS2'
                    else:
                        chemps2 = 'CHEMPS2'
                    self.cfg.update('configopts', " -DENABLE_%s=ON" % chemps2)
                    if LooseVersion(self.version) < LooseVersion("1.2"):
                        self.cfg.update('configopts', " -DCHEMPS2_ROOT=%s" % chempsroot)
                    else:
                        self.cfg.update('configopts', " -DCMAKE_INSIST_FIND_PACKAGE_CheMPS2=ON "
                                        "-DCheMPS2_DIR=%s/share/cmake/CheMPS2" % chempsroot)

                #  Be aware, PSI4 wants exact versions of the following deps! built with CMake!!
                #  If you want to use non-CMake build versions, the you have to provide the
                #  corresponding Find<library-name>.cmake scripts
                #  In PSI4 version 1.2.1, you can check the corresponding CMakeLists.txt file
                #  in external/upstream/<library-name>/
                if LooseVersion(self.version) >= LooseVersion("1.2"):
                    for dep in ['libxc', 'Libint', 'pybind11', 'gau2grid']:
                        deproot = get_software_root(dep)
                        if deproot:
                            self.cfg.update('configopts', " -DCMAKE_INSIST_FIND_PACKAGE_%s=ON" % dep)
                            dep_dir = os.path.join(deproot, 'share', 'cmake', dep)
                            self.cfg.update('configopts', " -D%s_DIR=%s " % (dep, dep_dir))

            CMakeMake.configure_step(self, srcdir=self.cfg['start_dir'])

    def install_step(self):
        """Custom install procedure for PSI."""
        super(EB_PSI, self).install_step()

        # the obj and unpacked sources must remain available for working with plugins
        try:
            for subdir in ['obj', self.psi_srcdir]:
                # copy symlinks as symlinks to work around broken symlinks
                shutil.copytree(os.path.join(self.builddir, subdir), os.path.join(self.installdir, subdir),
                                symlinks=True)
        except OSError as err:
            raise EasyBuildError("Failed to copy obj and unpacked sources to install dir: %s", err)

    def test_step(self):
        """
        Run the testsuite of PSI4
        """
        testdir = tempfile.mkdtemp()
        env.setvar('PSI_SCRATCH', testdir)
        if self.name == 'PSI4' and LooseVersion(self.version) >= LooseVersion("1.2"):
            if self.cfg['runtest']:
                paracmd = ''
                # Run ctest parallel, but limit to maximum 4 jobs (in case of slow disks)
                if self.cfg['parallel']:
                    if self.cfg['parallel'] > 4:
                        paracmd = '-j 4'
                    else:
                        paracmd = "-j %s" % self.cfg['parallel']
                cmd = "ctest %s %s" % (paracmd, self.cfg['runtest'])
                run_cmd(cmd, log_all=True, simple=False)
        else:
            super(EB_PSI, self).test_step()

        try:
            shutil.rmtree(testdir)
        except OSError as err:
            raise EasyBuildError("Failed to remove test directory %s: %s", testdir, err)

    def sanity_check_step(self):
        """Custom sanity check for PSI."""
        custom_paths = {
            'files': ['bin/psi4'],
            'dirs': ['include', ('share/psi', 'share/psi4')],
        }
        super(EB_PSI, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_extra(self):
        """Custom variables for PSI module."""
        txt = super(EB_PSI, self).make_module_extra()
        share_dir = os.path.join(self.installdir, 'share')
        if os.path.exists(share_dir):
            psi4datadir = glob.glob(os.path.join(share_dir, 'psi*'))
            if len(psi4datadir) == 1:
                txt += self.module_generator.set_environment('PSI4DATADIR', psi4datadir[0])
            else:
                raise EasyBuildError("Failed to find exactly one PSI4 data dir: %s", psi4datadir)
        return txt
