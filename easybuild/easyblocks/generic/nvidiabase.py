##
# Copyright 2015-2025 Bart Oldeman
# Copyright 2016-2025 Forschungszentrum Juelich
#
# This file is triple-licensed under GPLv2 (see below), MIT, and
# BSD three-clause licenses.
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
EasyBuild support for installing NVIDIA HPC SDK

@author: Bart Oldeman (McGill University, Calcul Quebec, Compute Canada)
@author: Damian Alvarez (Forschungszentrum Juelich)
@author: Andreas Herten (Forschungszentrum Juelich)
@author: Alex Domingo (Vrije Universiteit Brussel)
"""
import fileinput
import glob
import os
import re
import stat
import sys
import tempfile

import easybuild.tools.toolchain as toolchain
from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools import LooseVersion
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.config import build_option
from easybuild.tools.filetools import adjust_permissions, remove, symlink, write_file
from easybuild.tools.modules import MODULE_LOAD_ENV_HEADERS, get_software_root, get_software_version
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.systemtools import AARCH64, X86_64, get_cpu_architecture, get_shared_lib_ext
from easybuild.tools.toolchain.mpi import get_mpi_cmd_template

# contents for siterc file to make PGI/NVHPC pick up $LIBRARY_PATH
# cfr. https://www.pgroup.com/support/link.htm#lib_path_ldflags
SITERC_LIBRARY_PATH = """
# get the value of the environment variable LIBRARY_PATH
variable LIBRARY_PATH is environment(LIBRARY_PATH);

# split this value at colons, separate by -L, prepend 1st one by -L
variable library_path is
default($if($LIBRARY_PATH,-L$replace($LIBRARY_PATH,":", -L)));

# add the -L arguments to the link line
append LDLIBARGS=$library_path;

# also include the location where libm & co live on Debian-based systems
# cfr. https://github.com/easybuilders/easybuild-easyblocks/pull/919
append LDLIBARGS=-L/usr/lib/x86_64-linux-gnu;
"""

# contents for minimal example compiled in sanity check, used to catch issue
# seen in: https://github.com/easybuilders/easybuild-easyblocks/pull/3240
NVHPC_MINIMAL_EXAMPLE = """
#include <ranges>

int main(){ return 0; }
"""


class NvidiaBase(PackedBinary):
    """
    Core support for installing the NVIDIA HPC SDK (NVHPC)
    """

    CUDA_VERSION_GLOB = '[0-9][0-9].[0-9]*'

    @staticmethod
    def extra_options():
        extra_vars = {
            'default_cuda_version':      [None, "CUDA Version to be used as default (eg. 12.6)", CUSTOM],
            'module_add_cuda':           [False, "Add NVHPC's CUDA to module", CUSTOM],
            'module_add_math_libs':      [False, "Add NVHPC's math libraries to module", CUSTOM],
            'module_add_nccl':           [False, "Add NVHPC's NCCL library to module", CUSTOM],
            'module_add_nvshmem':        [False, "Add NVHPC's NVSHMEM library to module", CUSTOM],
            'module_add_profilers':      [False, "Add NVHPC's NVIDIA Profilers to module", CUSTOM],
            'module_byo_compilers':      [False, "BYO Compilers: Remove compilers from module", CUSTOM],
            'module_nvhpc_own_mpi':      [False, "Add NVHPC's packaged OpenMPI to module", CUSTOM]
        }
        return PackedBinary.extra_options(extra_vars)

    def _get_default_cuda(self):
        """Return suitable default CUDA version for this installation"""
        # determine supported CUDA versions from sources
        cuda_subdir_glob = os.path.join(self.install_subdir, 'cuda', self.CUDA_VERSION_GLOB)
        cuda_builddir_glob = os.path.join(self.builddir, 'nvhpc_*', 'install_components', cuda_subdir_glob)
        supported_cuda_versions = [os.path.basename(cuda_dir) for cuda_dir in glob.glob(cuda_builddir_glob)]
        if not supported_cuda_versions:
            # try install dir in case of module-only installs
            cuda_installdir_glob = os.path.join(self.installdir, cuda_subdir_glob)
            supported_cuda_versions = [os.path.basename(cuda_dir) for cuda_dir in glob.glob(cuda_installdir_glob)]
            if not supported_cuda_versions:
                raise EasyBuildError(f"Failed to determine supported versions of CUDA in {self.name}-{self.version}")

        supported_cuda_commasep = ', '.join(supported_cuda_versions)
        self.log.debug(
            f"Found the following supported CUDA versions by {self.name}-{self.version}: {supported_cuda_commasep}"
        )

        # default CUDA version from nvidia-compilers
        if get_software_version("nvidia-compilers"):
            nvcomp_cuda_version = os.getenv("EBNVHPCCUDAVER", None)
            if nvcomp_cuda_version is None:
                raise EasyBuildError("Missing $EBNVHPCCUDAVER in environment from 'nvidia-compilers' module")
            if nvcomp_cuda_version not in supported_cuda_versions:
                raise EasyBuildError(
                    f"CUDA version '{nvcomp_cuda_version}' in 'nvidia-compilers' not supported by "
                    f"{self.name}-{self.version}: {supported_cuda_commasep}"
                )
            self.log.info(
                f"Using version '{nvcomp_cuda_version}' of loaded nvidia-compilers dependency "
                f"as 'default_cuda_version' of {self.name}"
            )
            return nvcomp_cuda_version

        # default CUDA version from external CUDA
        cuda_dependency_version = get_software_version("CUDA")
        if cuda_dependency_version:
            external_cuda_version = '.'.join(cuda_dependency_version.split('.')[:2])
            if external_cuda_version not in supported_cuda_versions:
                raise EasyBuildError(
                    f"CUDA version '{external_cuda_version}' from external CUDA not supported by "
                    f"{self.name}-{self.version}: {supported_cuda_commasep}"
                )
            self.log.info(
                f"Using version '{external_cuda_version}' of loaded CUDA dependency "
                f"as 'default_cuda_version' of {self.name}"
            )
            return external_cuda_version

        # default CUDA version set in configuration
        default_cuda_version = self.cfg['default_cuda_version']
        if default_cuda_version is not None:
            if default_cuda_version not in supported_cuda_versions:
                raise EasyBuildError(
                    f"Selecte default CUDA version '{default_cuda_version}' not supported by "
                    f"{self.name}-{self.version}: {supported_cuda_commasep}"
                )
            return default_cuda_version

        # default CUDA version undefined, pick one if obvious
        if len(supported_cuda_versions) == 1:
            default_cuda_version = supported_cuda_versions[0]
            self.log.info(
                f"Missing 'default_cuda_version' or CUDA dependency. Using CUDA version '{default_cuda_version}' "
                f"as it is the only version supported by {self.name}-{self.version}."
            )
            return default_cuda_version

        error_msg = f"Missing 'default_cuda_version' or CUDA dependency for {self.name}. "
        error_msg += "Either add CUDA as dependency or manually define 'default_cuda_version'."
        error_msg += "You can edit the easyconfig file, "
        error_msg += "or use 'eb --try-amend=default_cuda_version=<version>'."
        raise EasyBuildError(error_msg)

    def _get_default_compute_capability(self):
        """Return suitable CUDA compute capability for this installation"""
        # Parse default_compute_capability from different sources (CLI has priority)
        ec_default_compute_capability = self.cfg['cuda_compute_capabilities']
        cfg_default_compute_capability = build_option('cuda_compute_capabilities')
        if cfg_default_compute_capability is not None:
            default_compute_capability = cfg_default_compute_capability
        elif ec_default_compute_capability and ec_default_compute_capability is not None:
            default_compute_capability = ec_default_compute_capability
        else:
            error_msg = "Missing CUDA Compute Capability for installation of NVHPC."
            error_msg += "Please provide it in the easyconfig file with 'cuda_compute_capabilities=\"x.x\"',"
            error_msg += "or use 'eb --cuda-compute-capabilities=x.x' from the command line."
            raise EasyBuildError(error_msg)

        # NVHPC needs a single value as default CC
        if isinstance(default_compute_capability, list):
            _before_default_compute_capability = default_compute_capability
            default_compute_capability = _before_default_compute_capability[0]
            if len(_before_default_compute_capability) > 1:
                warning_msg = f"Replaced list of compute capabilities {_before_default_compute_capability} "
                warning_msg += f"with first element of list: {default_compute_capability}"
                print_warning(warning_msg)
        if not isinstance(default_compute_capability, str):
            errmsg = f"Unexpected non-string value encountered for compute capability: {default_compute_capability}"
            raise EasyBuildError(errmsg)

        self.log.info(f"Using CUDA compute capability '{default_compute_capability}' for {self.name}-{self.version}")
        return default_compute_capability

    def _update_nvhpc_environment(self):
        """Update module load environment according to easyblock configuration options"""
        # Set default minimal search paths
        self.module_load_environment.PATH.remove(os.path.join(self.install_subdir, 'compilers', 'bin'))
        self.module_load_environment.CMAKE_MODULE_PATH = os.path.join(self.install_subdir, 'cmake')
        # compilers can find their own headers, unset $CPATH (and equivalents)
        self.module_load_environment.set_alias_vars(MODULE_LOAD_ENV_HEADERS, [])

        # Internal Nvidia compilers: no 'nvidia-compilers' dep or BYO option
        if not self.cfg['module_byo_compilers'] and not get_software_version("nvidia-compilers"):
            self.module_load_environment.PATH = os.path.join(self.install_subdir, 'compilers', 'bin')
            self.module_load_environment.LD_LIBRARY_PATH = os.path.join(self.install_subdir, 'compilers', 'lib')
            self.module_load_environment.CMAKE_PREFIX_PATH = os.path.join(self.install_subdir, 'compilers')
            self.module_load_environment.MANPATH = os.path.join(self.install_subdir, 'compilers', 'man')
            self.module_load_environment.XDG_DATA_DIRS = os.path.join(self.install_subdir, 'compilers', 'share')

        # Own MPI: enable OpenMPI bundled in NVHPC
        if self.cfg['module_nvhpc_own_mpi']:
            mpi_basedir = os.path.join(self.install_subdir, "comm_libs", "mpi")
            self.module_load_environment.PATH.append(os.path.join(mpi_basedir, 'bin'))
            self.module_load_environment.LD_LIBRARY_PATH.append(os.path.join(mpi_basedir, 'lib'))
            for cpp_header in self.module_load_environment.alias(MODULE_LOAD_ENV_HEADERS):
                cpp_header.append(os.path.join(mpi_basedir, 'include'))

        # Math Libraries: enable math libraries bundled in NVHPC
        if self.cfg['module_add_math_libs']:
            math_basedir = os.path.join(self.install_subdir, "math_libs")
            self.module_load_environment.LD_LIBRARY_PATH.append(os.path.join(math_basedir, 'lib64'))
            for cpp_header in self.module_load_environment.alias(MODULE_LOAD_ENV_HEADERS):
                cpp_header.append(os.path.join(math_basedir, 'include'))

        # GPU Profilers: enable NVIDIA's GPU profilers (Nsight Compute/Nsight Systems)
        if self.cfg['module_add_profilers']:
            profilers_basedir = os.path.join(self.install_subdir, "profilers")
            self.module_load_environment.PATH.extend([
                os.path.join(profilers_basedir, 'Nsight_Compute'),
                os.path.join(profilers_basedir, 'Nsight_Systems', 'bin'),
            ])

        # NCCL: enable NCCL bundled in NVHPC
        if self.cfg['module_add_nccl']:
            nccl_basedir = os.path.join(self.install_subdir, "comm_libs", "nccl")
            self.module_load_environment.LD_LIBRARY_PATH.append(os.path.join(nccl_basedir, 'lib'))
            for cpp_header in self.module_load_environment.alias(MODULE_LOAD_ENV_HEADERS):
                cpp_header.append(os.path.join(nccl_basedir, 'include'))

        # NVSHMEM: enable NVSHMEM bundled in NVHPC
        if self.cfg['module_add_nvshmem']:
            nvshmem_basedir = os.path.join(self.install_subdir, "comm_libs", "nvshmem")
            self.module_load_environment.LD_LIBRARY_PATH.append(os.path.join(nvshmem_basedir, 'lib'))
            for cpp_header in self.module_load_environment.alias(MODULE_LOAD_ENV_HEADERS):
                cpp_header.append(os.path.join(nvshmem_basedir, 'include'))

        # CUDA: enable CUDA bundled in NVHPC
        if self.cfg['module_add_cuda']:
            cuda_basedir = os.path.join(self.install_subdir, "cuda")
            self.module_load_environment.PATH.append(os.path.join(cuda_basedir, 'bin'))
            self.module_load_environment.LD_LIBRARY_PATH.append(os.path.join(cuda_basedir, 'lib64'))
            for cpp_header in self.module_load_environment.alias(MODULE_LOAD_ENV_HEADERS):
                cpp_header.append(os.path.join(cuda_basedir, 'include'))
            # emulate environment from standalone CUDA
            cuda_home = os.path.join(self.installdir, cuda_basedir)
            self.cfg.update('modextravars', {
                'CUDA_HOME': cuda_home,
                'CUDA_ROOT': cuda_home,
                'CUDA_PATH': cuda_home,
            })
        elif get_software_version('CUDA'):
            # NVHPC 22.7+ requires the variable NVHPC_CUDA_HOME for external CUDA. CUDA_HOME has been deprecated.
            if LooseVersion(self.version) >= LooseVersion('22.7'):
                self.cfg.update('modextravars', {'NVHPC_CUDA_HOME': os.getenv('CUDA_HOME')})
                if self.cfg['module_nvhpc_own_mpi']:
                    # needed to use external CUDA with MPI in NVHPC
                    comm_libs_home = os.path.join(self.installdir, self.install_subdir, "comm_libs",
                                                  self.default_cuda_version)
                    self.cfg.update('modextravars', {'NVCOMPILER_COMM_LIBS_HOME': comm_libs_home})

        # In the end, set LIBRARY_PATH equal to LD_LIBRARY_PATH
        self.module_load_environment.LIBRARY_PATH = self.module_load_environment.LD_LIBRARY_PATH

    def __init__(self, *args, **kwargs):
        """Easyblock constructor, define custom class variables specific to NVHPC."""
        super().__init__(*args, **kwargs)

        # EULA for NVHPC must be accepted via --accept-eula-for EasyBuild configuration option,
        # or via 'accept_eula = True' in easyconfig file
        self.check_accepted_eula(more_info='https://docs.nvidia.com/hpc-sdk/eula/index.html', name="NVHPC")

        host_cpu_arch = get_cpu_architecture()
        if host_cpu_arch == X86_64:
            nv_arch_tag = 'x86_64'
        elif host_cpu_arch == AARCH64:
            nv_arch_tag = 'aarch64'
        else:
            raise EasyBuildError("Unsupported CPU architecture for {self.name}-{self.version}: {host_arch_tag}")

        nv_sys_tag = f'Linux_{nv_arch_tag}'
        self.install_subdir = os.path.join(nv_sys_tag, self.version)

        self.default_cuda_version = None
        self.default_compute_capability = None

    def prepare_step(self, *args, **kwargs):
        """Prepare environment for installation."""
        super().prepare_step(*args, **kwargs)

        # Check if we need to enable bundled CUDA
        if not get_software_version("CUDA") and not get_software_version("nvidia-compilers"):
            self.cfg['module_add_cuda'] = True
        elif self.cfg['module_add_cuda']:
            raise EasyBuildError(
                "Option 'module_add_cuda' is not compatible with CUDA loaded through dependencies"
            )

        self.default_cuda_version = self._get_default_cuda()
        self.cfg.update('modextravars', {'EBNVHPCCUDAVER': self.default_cuda_version})

        self.default_compute_capability = self._get_default_compute_capability()
        self.cfg.update('modextravars', {'EBNVHPCCUDACC': self.default_compute_capability})

        self.cfg.update('modextravars', {'NVHPC': self.installdir})

        self._update_nvhpc_environment()

    def install_step(self):
        """Install by running install command."""

        nvhpc_env_vars = {
            'NVHPC_INSTALL_DIR': self.installdir,
            'NVHPC_SILENT': 'true',
            'NVHPC_DEFAULT_CUDA': str(self.default_cuda_version),  # e.g. 10.2, 11.0
            # NVHPC_STDPAR_CUDACC uses single value CC without dot-divider (e.g. 70, 80)
            'NVHPC_STDPAR_CUDACC': str(self.default_compute_capability.replace('.', ''))
            }
        cmd_env = ' '.join([f'{name}={value}' for name, value in sorted(nvhpc_env_vars.items())])
        run_shell_cmd(f"{cmd_env} ./install")

        # make sure localrc uses GCC in PATH, not always the system GCC, and does not use a system g77 but gfortran
        install_abs_subdir = os.path.join(self.installdir, self.install_subdir)
        compilers_subdir = os.path.join(install_abs_subdir, "compilers")
        makelocalrc_filename = os.path.join(compilers_subdir, "bin", "makelocalrc")
        for line in fileinput.input(makelocalrc_filename, inplace='1', backup='.orig'):
            line = re.sub(r"^PATH=/", r"#PATH=/", line)
            sys.stdout.write(line)

        if LooseVersion(self.version) >= LooseVersion('22.9'):
            bin_subdir = os.path.join(compilers_subdir, "bin")
            cmd = f"{makelocalrc_filename} -x {bin_subdir}"
        else:
            cmd = f"{makelocalrc_filename} -x {compilers_subdir} -g77 /"

        run_shell_cmd(cmd)

        # If an OS libnuma is NOT found, makelocalrc creates symbolic links to libpgnuma.so
        # If we use the EB libnuma, delete those symbolic links to ensure they are not used
        if get_software_root("numactl"):
            for filename in ["libnuma.so", "libnuma.so.1"]:
                path = os.path.join(compilers_subdir, "lib", filename)
                if os.path.islink(path):
                    os.remove(path)

        if LooseVersion(self.version) < LooseVersion('21.3'):
            # install (or update) siterc file to make NVHPC consider $LIBRARY_PATH
            siterc_path = os.path.join(compilers_subdir, 'bin', 'siterc')
            write_file(siterc_path, SITERC_LIBRARY_PATH, append=True)
            self.log.info("Appended instructions to pick up $LIBRARY_PATH to siterc file at %s: %s",
                          siterc_path, SITERC_LIBRARY_PATH)

        # Cleanup unnecessary installation files
        abs_install_subdir = os.path.join(self.installdir, self.install_subdir)
        if not self.cfg['module_nvhpc_own_mpi']:
            mpi_dir_globs = [
                os.path.join(abs_install_subdir, 'comm_libs', 'openmpi*'),
                os.path.join(abs_install_subdir, 'comm_libs', self.CUDA_VERSION_GLOB, 'openmpi*'),
                os.path.join(abs_install_subdir, 'comm_libs',  'hpcx*'),
                os.path.join(abs_install_subdir, 'comm_libs', self.CUDA_VERSION_GLOB, 'hpcx*'),
            ]
            remove([dir_path for dir_glob in mpi_dir_globs for dir_path in glob.glob(dir_glob)])
            remove(os.path.join(abs_install_subdir, 'comm_libs',  'mpi'))
        if not self.cfg['module_add_nccl']:
            nccl_dir_glob = os.path.join(abs_install_subdir, 'comm_libs', self.CUDA_VERSION_GLOB, 'nccl')
            remove(glob.glob(nccl_dir_glob))
            remove(os.path.join(abs_install_subdir, 'comm_libs',  'nccl'))
        if not self.cfg['module_add_nvshmem']:
            shmem_dir_glob = os.path.join(abs_install_subdir, 'comm_libs', self.CUDA_VERSION_GLOB, 'nvshmem')
            remove(glob.glob(shmem_dir_glob))
            remove(os.path.join(abs_install_subdir, 'comm_libs',  'nvshmem'))
        if not self.cfg['module_add_math_libs']:
            remove(os.path.join(abs_install_subdir, 'math_libs'))
        if not self.cfg['module_add_profilers']:
            remove(os.path.join(abs_install_subdir, 'profilers'))
        if not self.cfg['module_add_cuda']:
            # remove everything included in each cuda subdir, but leave the top CUDA dirs
            # as they are needed to determine supported versions (e.g. module-only installs)
            cuda_dir_glob = os.path.join(abs_install_subdir, 'cuda', self.CUDA_VERSION_GLOB, '*')
            remove(glob.glob(cuda_dir_glob))
            cuda_links_glob = os.path.join(abs_install_subdir, 'cuda', '[a-z]*')
            remove(glob.glob(cuda_links_glob))

        nvcomp_root = get_software_root("nvidia-compilers")
        if nvcomp_root:
            # link external compilers from nvidia-compilers
            current_comp_dir = os.path.join(abs_install_subdir, 'compilers')
            remove(current_comp_dir)
            nvcomp_comp_dir = os.path.join(nvcomp_root, self.install_subdir, 'compilers')
            nvcomp_link_path = os.path.relpath(nvcomp_comp_dir, start=abs_install_subdir)
            symlink(nvcomp_link_path, current_comp_dir, use_abspath_source=False)

        # The cuda nvvp tar file has broken permissions
        adjust_permissions(self.installdir, stat.S_IWUSR, add=True, onlydirs=True)

    def sanity_check_step(self):
        """Custom sanity check for NVHPC"""
        prefix = self.install_subdir
        shlib_ext = get_shared_lib_ext()
        compiler_names = ['nvc', 'nvc++', 'nvfortran']

        nvhpc_files = [os.path.join(prefix, 'compilers', 'bin', x) for x in compiler_names]
        if LooseVersion(self.version) < LooseVersion('21.3'):
            nvhpc_files.append(os.path.join(prefix, 'compilers', 'bin', 'siterc'))
        nvhpc_dirs = [os.path.join(prefix, 'compilers', x) for x in ['bin', 'lib', 'include', 'man']]

        if self.cfg['module_nvhpc_own_mpi']:
            nvhpc_files.extend([
                os.path.join(prefix, 'comm_libs', 'mpi', 'bin', 'mpirun'),
                os.path.join(prefix, 'comm_libs', 'mpi', 'bin', 'mpicc'),
                os.path.join(prefix, 'comm_libs', 'mpi', 'bin', 'mpifort'),
            ])
        if self.cfg['module_add_math_libs']:
            nvhpc_files.extend([
                os.path.join(prefix, 'math_libs', 'lib64', f'libcublas.{shlib_ext}'),
                os.path.join(prefix, 'math_libs', 'lib64', f'libcufftw.{shlib_ext}'),
                os.path.join(prefix, 'math_libs', 'include', 'cublas.h'),
                os.path.join(prefix, 'math_libs', 'include', 'cufftw.h'),
            ])
        if self.cfg['module_add_cuda']:
            nvhpc_files.extend([
                os.path.join(prefix, 'cuda', self.default_cuda_version, 'bin', 'cuda-gdb'),
                os.path.join(prefix, 'cuda', self.default_cuda_version, 'lib64', f'libcudart.{shlib_ext}'),
            ])

        custom_paths = {
            'files': nvhpc_files,
            'dirs': nvhpc_dirs,
        }

        custom_commands = []
        if not self.cfg['module_byo_compilers']:
            custom_commands = [f"{compiler} -v" for compiler in compiler_names]
            if LooseVersion(self.version) >= LooseVersion('21'):
                # compile minimal example using -std=c++20 to catch issue where it picks up the wrong GCC
                # (as long as system gcc is < 9.0)
                # see: https://github.com/easybuilders/easybuild-easyblocks/pull/3240
                tmpdir = tempfile.mkdtemp()
                write_file(os.path.join(tmpdir, 'minimal.cpp'), NVHPC_MINIMAL_EXAMPLE)
                minimal_compiler_cmd = f"cd {tmpdir} && nvc++ -std=c++20 minimal.cpp -o minimal"
                custom_commands.append(minimal_compiler_cmd)

        if self.cfg['module_nvhpc_own_mpi']:
            tmpdir = tempfile.mkdtemp()
            # Check MPI compilers
            mpi_compiler_names = ['mpicc', 'mpicxx', 'mpifort', 'mpif90']
            custom_commands.extend([f"{comp} --version" for comp in mpi_compiler_names])
            # Build MPI test binary
            hpcx_dir = os.path.join(self.installdir, prefix, 'comm_libs', self.default_cuda_version, 'hpcx')
            mpi_hello_src = os.path.join(hpcx_dir, 'latest', 'ompi', 'tests', 'examples', 'hello_c.c')
            mpi_hello_exe = os.path.join(tmpdir, 'mpi_test_' + os.path.splitext(os.path.basename(mpi_hello_src))[0])
            self.log.info("Adding minimal MPI test program to sanity checks: %s", mpi_hello_exe)
            custom_commands.append(f"mpicc {mpi_hello_src} -o {mpi_hello_exe}")
            # Run MPI test binary
            mpi_cmd_tmpl, params = get_mpi_cmd_template(toolchain.NVHPC, {}, mpi_version=self.version)
            ranks = min(8, self.cfg.parallel)
            params.update({'nr_ranks': ranks, 'cmd': mpi_hello_exe})
            custom_commands.append(mpi_cmd_tmpl % params)

        super().sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
