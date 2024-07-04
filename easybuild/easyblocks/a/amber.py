##
# Copyright 2009-2024 Ghent University
# Copyright 2015-2024 Stanford University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://vscentrum.be/nl/en),
# the Hercules foundation (http://www.herculesstichting.be/in_English)
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
EasyBuild support for Amber, implemented as an easyblock

Original author: Benjamin Roberts (The University of Auckland)
Modified by Stephane Thiell (Stanford University) for Amber14
Enhanced/cleaned up by Kenneth Hoste (HPC-UGent)
CMake support (Amber 20) added by James Carpenter and Simon Branford (University of Birmingham)
"""
from easybuild.tools import LooseVersion
import os

import easybuild.tools.environment as env
import easybuild.tools.toolchain as toolchain
from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.easyblocks.generic.pythonpackage import det_pylibdir
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_cmd
from easybuild.tools.filetools import remove_dir, which


class EB_Amber(CMakeMake):
    """Easyblock for building and installing Amber"""

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to CMakeMake"""
        extra_vars = dict(CMakeMake.extra_options(extra_vars))
        extra_vars.update({
            # 'Amber': [True, "Build Amber in addition to AmberTools", CUSTOM],
            'patchlevels': ["latest", "(AmberTools, Amber) updates to be applied", CUSTOM],
            # The following is necessary because some patches to the Amber update
            # script update the update script itself, in which case it will quit
            # and insist on being run again. We don't know how many times will
            # be needed, but the number of times is patchlevel specific.
            'patchruns': [1, "Number of times to run Amber's update script before building", CUSTOM],
            # enable testing by default
            'runtest': [True, "Run tests after each build", CUSTOM],
            'static': [True, "Build statically linked executables", CUSTOM],
        })
        return CMakeMake.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Easyblock constructor: initialise class variables."""
        super(EB_Amber, self).__init__(*args, **kwargs)

        if LooseVersion(self.version) < LooseVersion('20'):
            # Build Amber <20 in install directory
            self.build_in_installdir = True
            env.setvar('AMBERHOME', self.installdir)

        self.pylibdir = None

        self.with_cuda = False
        self.with_mpi = False

    def extract_step(self):
        """Extract sources; strip off parent directory during unpack"""
        self.cfg.update('unpack_options', "--strip-components=1")
        super(EB_Amber, self).extract_step()

    def patch_step(self, *args, **kwargs):
        """Patch Amber using 'update_amber' tool, prior to applying listed patch files (if any)."""

        # figure out which Python command to use to run the update_amber script;
        # by default it uses 'python', but this may not be available (on CentOS 8 for example);
        # note that the dependencies are not loaded yet at this point, so we're at the mercy of the OS here...
        python_cmd = None
        for cand_python_cmd in ['python', 'python3', 'python2']:
            if which(cand_python_cmd):
                python_cmd = cand_python_cmd
                break

        if python_cmd is None:
            raise EasyBuildError("No suitable Python command found to run update_amber script!")

        if self.cfg['patchlevels'] == "latest":
            cmd = "%s ./update_amber --update" % python_cmd
            # Run as many times as specified. It is the responsibility
            # of the easyconfig author to get this right, especially if
            # he or she selects "latest". (Note: "latest" is not
            # recommended for this reason and others.)
            for _ in range(self.cfg['patchruns']):
                run_cmd(cmd, log_all=True)
        else:
            for (tree, patch_level) in zip(['AmberTools', 'Amber'], self.cfg['patchlevels']):
                if patch_level == 0:
                    continue
                cmd = "%s ./update_amber --update-to %s/%s" % (python_cmd, tree, patch_level)
                # Run as many times as specified. It is the responsibility
                # of the easyconfig author to get this right.
                for _ in range(self.cfg['patchruns']):
                    run_cmd(cmd, log_all=True)

        super(EB_Amber, self).patch_step(*args, **kwargs)

    def configure_step(self):
        """Apply the necessary CMake config opts."""

        if LooseVersion(self.version) < LooseVersion('19'):
            # Configuring Amber <19 is done in install step.
            return

        # CMake will search a previous install directory for Amber-compiled libs. We will therefore
        # manually remove the install directory prior to configuration.
        remove_dir(self.installdir)

        external_libs_list = []

        mpiroot = get_software_root(self.toolchain.MPI_MODULE_NAME[0])
        if mpiroot and self.toolchain.options.get('usempi', None):
            self.with_mpi = True
            self.cfg.update('configopts', '-DMPI=TRUE')

        if self.toolchain.options.get('openmp', None):
            self.cfg.update('configopts', '-DOPENMP=TRUE')

        # note: for Amber 20, a patch is required to fix the CMake scripts so they're aware of FlexiBLAS:
        # - cmake/patched-cmake-modules/FindBLASFixed.cmake
        # - cmake/patched-cmake-modules/FindLAPACKFixed.cmake
        flexiblas_root = get_software_root('FlexiBLAS')
        if flexiblas_root:
            self.cfg.update('configopts', '-DBLA_VENDOR=FlexiBLAS')
        else:
            openblas_root = get_software_root('OpenBLAS')
            if openblas_root:
                self.cfg.update('configopts', '-DBLA_VENDOR=OpenBLAS')

        cudaroot = get_software_root('CUDA')
        if cudaroot:
            self.with_cuda = True
            self.cfg.update('configopts', '-DCUDA=TRUE')
            if get_software_root('NCCL'):
                self.cfg.update('configopts', '-DNCCL=TRUE')
                external_libs_list.append('nccl')

        pythonroot = get_software_root('Python')
        if pythonroot:
            self.cfg.update('configopts', '-DDOWNLOAD_MINICONDA=FALSE')
            self.cfg.update('configopts', '-DPYTHON_EXECUTABLE=%s' % os.path.join(pythonroot, 'bin', 'python'))

            self.pylibdir = det_pylibdir()
            pythonpath = os.environ.get('PYTHONPATH', '')
            env.setvar('PYTHONPATH', os.pathsep.join([os.path.join(self.installdir, self.pylibdir), pythonpath]))

        if get_software_root('FFTW'):
            external_libs_list.append('fftw')
        if get_software_root('netCDF'):
            external_libs_list.append('netcdf')
        if get_software_root('netCDF-Fortran'):
            external_libs_list.append('netcdf-fortran')
        if get_software_root('zlib'):
            external_libs_list.append('zlib')
        if get_software_root('Boost'):
            external_libs_list.append('boost')
        if get_software_root('PnetCDF'):
            external_libs_list.append('pnetcdf')

        # Force libs for available deps (see cmake/3rdPartyTools.cmake in Amber source for list of 3rd party libs)
        # This provides an extra layer of checking but should already be handled by TRUST_SYSTEM_LIBS=TRUE
        external_libs = ";".join(external_libs_list)
        self.cfg.update('configopts', "-DFORCE_EXTERNAL_LIBS='%s'" % external_libs)

        if get_software_root('FFTW') or get_software_root('imkl'):
            self.cfg.update('configopts', '-DUSE_FFT=TRUE')

        # Set standard compile options
        self.cfg.update('configopts', '-DCHECK_UPDATES=FALSE')
        self.cfg.update('configopts', '-DAPPLY_UPDATES=FALSE')
        self.cfg.update('configopts', '-DTRUST_SYSTEM_LIBS=TRUE')
        self.cfg.update('configopts', '-DCOLOR_CMAKE_MESSAGES=FALSE')

        # Amber recommend running the tests from the sources, rather than putting in installation dir
        # due to size. We handle tests under the install step
        self.cfg.update('configopts', '-DINSTALL_TESTS=FALSE')

        self.cfg.update('configopts', '-DCOMPILER=AUTO')

        # configure using cmake
        super(EB_Amber, self).configure_step()

    def build_step(self):
        """Build Amber"""
        if LooseVersion(self.version) < LooseVersion('20'):
            # Building Amber < 20 is done in install step.
            return

        super(EB_Amber, self).build_step()

    def test_step(self):
        """Testing Amber build is done in install step."""
        pass

    def configuremake_install_step(self):
        """Custom build, test & install procedure for Amber <20."""
        # unset $LIBS since it breaks the build
        env.unset_env_vars(['LIBS'])

        # define environment variables for MPI, BLAS/LAPACK & dependencies
        mklroot = get_software_root('imkl')
        flexiblas_root = get_software_root('FlexiBLAS')
        openblas_root = get_software_root('OpenBLAS')
        if mklroot:
            env.setvar('MKL_HOME', os.getenv('MKLROOT'))
        elif flexiblas_root or openblas_root:
            lapack = os.getenv('LIBLAPACK')
            if lapack is None:
                raise EasyBuildError("$LIBLAPACK for OpenBLAS or FlexiBLAS not defined in build environment!")
            else:
                env.setvar('GOTO', lapack)

        mpiroot = get_software_root(self.toolchain.MPI_MODULE_NAME[0])
        if mpiroot and self.toolchain.options.get('usempi', None):
            env.setvar('MPI_HOME', mpiroot)
            self.with_mpi = True
            if self.toolchain.mpi_family() == toolchain.INTELMPI:
                self.mpi_option = '-intelmpi'
            else:
                self.mpi_option = '-mpi'

        common_configopts = [self.cfg['configopts'], '--no-updates']

        if get_software_root('X11') is None:
            common_configopts.append('-noX11')

        if self.name == 'Amber' and self.cfg['static']:
            common_configopts.append('-static')

        netcdfroot = get_software_root('netCDF')
        if netcdfroot:
            common_configopts.extend(["--with-netcdf", netcdfroot])

        netcdf_fort_root = get_software_root('netCDF-Fortran')
        if netcdf_fort_root:
            common_configopts.extend(["--with-netcdf-fort", netcdf_fort_root])

        pythonroot = get_software_root('Python')
        if pythonroot:
            common_configopts.extend(["--with-python", os.path.join(pythonroot, 'bin', 'python')])

            self.pylibdir = det_pylibdir()
            pythonpath = os.environ.get('PYTHONPATH', '')
            env.setvar('PYTHONPATH', os.pathsep.join([os.path.join(self.installdir, self.pylibdir), pythonpath]))

        comp_fam = self.toolchain.comp_family()
        if comp_fam == toolchain.INTELCOMP:
            comp_str = 'intel'

        elif comp_fam == toolchain.GCC:
            comp_str = 'gnu'

        else:
            raise EasyBuildError("Don't know how to compile with compiler family '%s' -- check EasyBlock?", comp_fam)

        # The NAB compiles need openmp flag
        if self.toolchain.options.get('openmp', None):
            env.setvar('CUSTOMBUILDFLAGS', self.toolchain.get_flag('openmp'))

        # compose list of build targets
        build_targets = [('', 'test')]

        if self.with_mpi:
            build_targets.append((self.mpi_option, 'test.parallel'))
            # hardcode to 4 MPI processes, minimal required to run all tests
            env.setvar('DO_PARALLEL', self.toolchain.mpi_cmd_for('', 4))

        cudaroot = get_software_root('CUDA')
        if cudaroot:
            env.setvar('CUDA_HOME', cudaroot)
            self.with_cuda = True
            build_targets.append(('-cuda', 'test.cuda'))
            if self.with_mpi:
                build_targets.append(("-cuda %s" % self.mpi_option, 'test.cuda_parallel'))

        ld_lib_path = os.environ.get('LD_LIBRARY_PATH', '')
        env.setvar('LD_LIBRARY_PATH', os.pathsep.join([os.path.join(self.installdir, 'lib'), ld_lib_path]))

        for flag, testrule in build_targets:
            # configure
            cmd = "%s ./configure %s" % (self.cfg['preconfigopts'], ' '.join(common_configopts + [flag, comp_str]))
            (out, _) = run_cmd(cmd, log_all=True, simple=False)

            # build in situ using 'make install'
            # note: not 'build'
            super(EB_Amber, self).install_step()

            # test
            if self.cfg['runtest']:
                run_cmd("make %s" % testrule, log_all=True, simple=False)

            # clean, overruling the normal 'build'
            run_cmd("make clean")

    def install_step(self):
        """Install procedure for Amber."""

        if LooseVersion(self.version) < LooseVersion('20'):
            # pass into the configuremake build, install, and test method for Amber <20
            self.configuremake_install_step()
            return

        super(EB_Amber, self).install_step()

        # Run the tests located in the build directory
        if self.cfg['runtest']:
            pretestcommands = 'source %s/amber.sh && cd %s' % (self.installdir, self.builddir)

            # serial tests
            run_cmd("%s && make test.serial" % pretestcommands, log_all=True, simple=True)
            if self.with_cuda:
                (out, ec) = run_cmd("%s && make test.cuda_serial" % pretestcommands, log_all=True, simple=False)
                if ec > 0:
                    self.log.warning("Check the output of the Amber cuda tests for possible failures")

            if self.with_mpi:
                # Hard-code parallel tests to use 4 threads
                env.setvar("DO_PARALLEL", self.toolchain.mpi_cmd_for('', 4))
                (out, ec) = run_cmd("%s && make test.parallel" % pretestcommands, log_all=True, simple=False)
                if ec > 0:
                    self.log.warning("Check the output of the Amber parallel tests for possible failures")

            if self.with_mpi and self.with_cuda:
                # Hard-code CUDA parallel tests to use 2 threads
                env.setvar("DO_PARALLEL", self.toolchain.mpi_cmd_for('', 2))
                (out, ec) = run_cmd("%s && make test.cuda_parallel" % pretestcommands, log_all=True, simple=False)
                if ec > 0:
                    self.log.warning("Check the output of the Amber cuda_parallel tests for possible failures")

    def sanity_check_step(self):
        """Custom sanity check for Amber."""
        binaries = ['sander', 'tleap']
        if self.name == 'Amber':
            binaries.append('pmemd')
            if self.with_cuda:
                binaries.append('pmemd.cuda')
                if self.with_mpi:
                    if LooseVersion(self.version) < LooseVersion('20'):
                        binaries.append('pmemd.cuda.MPI')
                    else:
                        binaries.append('pmemd.cuda_DPFP.MPI')

        if self.with_mpi:
            binaries.extend(['sander.MPI'])
            if self.name == 'Amber':
                binaries.append('pmemd.MPI')

        custom_paths = {
            'files': [os.path.join(self.installdir, 'bin', binary) for binary in binaries],
            'dirs': [],
        }
        super(EB_Amber, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_extra(self):
        """Add module entries specific to Amber/AmberTools"""
        txt = super(EB_Amber, self).make_module_extra()

        txt += self.module_generator.set_environment('AMBERHOME', self.installdir)
        if self.pylibdir:
            txt += self.module_generator.prepend_paths('PYTHONPATH', self.pylibdir)

        return txt
