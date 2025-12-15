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
import os
import re
import stat
import sys
import tempfile
from glob import glob

import easybuild.tools.toolchain as toolchain
from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools import LooseVersion
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.config import build_option
from easybuild.tools.filetools import adjust_permissions, remove, symlink
from easybuild.tools.filetools import write_file, apply_regex_substitutions, resolve_path
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
            'default_cuda_version':      [None, "CUDA version used by default in this toolchain", CUSTOM],
            'module_add_cuda':           [False, "Add NVHPC's CUDA to module", CUSTOM],
            'module_add_math_libs':      [False, "Add NVHPC's math libraries to module", CUSTOM],
            'module_add_nccl':           [False, "Add NVHPC's NCCL library to module", CUSTOM],
            'module_add_nvshmem':        [False, "Add NVHPC's NVSHMEM library to module", CUSTOM],
            'module_add_profilers':      [False, "Add NVHPC's NVIDIA Profilers to module", CUSTOM],
            'module_byo_compilers':      [False, "BYO Compilers: Remove compilers from module", CUSTOM],
            'module_nvhpc_own_mpi':      [False, "Add NVHPC's packaged OpenMPI to module", CUSTOM]
        }
        return PackedBinary.extra_options(extra_vars)

    def _get_active_cuda(self):
        """
        Return the active single version of CUDA for this installation
        Preference order:
        1. CUDA version set by nvidia-compilers
        2. CUDA version of external CUDA
        3. CUDA version set by option 'default_cuda_version'
        4. CUDA version supported by current install (if obvious)
        """
        # determine supported CUDA versions from sources
        cuda_subdir_glob = os.path.join(self.install_subdir, 'cuda', self.CUDA_VERSION_GLOB)
        cuda_builddir_glob = os.path.join(self.builddir, 'nvhpc_*', 'install_components', cuda_subdir_glob)
        supported_cuda_versions = [os.path.basename(cuda_dir) for cuda_dir in glob(cuda_builddir_glob)]
        if not supported_cuda_versions:
            # try install dir in case of module-only installs
            cuda_installdir_glob = os.path.join(self.installdir, cuda_subdir_glob)
            supported_cuda_versions = [os.path.basename(cuda_dir) for cuda_dir in glob(cuda_installdir_glob)]

        if supported_cuda_versions:
            supported_cuda_commasep = ', '.join(supported_cuda_versions)
            self.log.debug(
                f"Found the following supported CUDA versions by {self.name}-{self.version}: {supported_cuda_commasep}"
            )
        else:
            # we cannot error out here, otherwise it forces having the sources of NVHPC to test this easyblock
            print_warning(
                f"Failed to determine supported versions of CUDA in {self.name}-{self.version}."
                "Continuing installation without further checks on CUDA version."
            )

        # Only use major.minor version as default CUDA version
        def filter_major_minor(version):
            return '.'.join(version.split('.')[:2])

        # default CUDA version from nvidia-compilers
        if get_software_version("nvidia-compilers"):
            nvcomp_cuda_version = os.getenv("EBNVHPCCUDAVER", None)
            if nvcomp_cuda_version is None:
                raise EasyBuildError("Missing $EBNVHPCCUDAVER in environment from 'nvidia-compilers' module")
            if supported_cuda_versions and nvcomp_cuda_version not in supported_cuda_versions:
                raise EasyBuildError(
                    f"CUDA version '{nvcomp_cuda_version}' in 'nvidia-compilers' not supported by "
                    f"{self.name}-{self.version}: {supported_cuda_commasep}"
                )
            self.log.info(
                f"Using CUDA version '{nvcomp_cuda_version}' from nvidia-compilers dependency "
                f"as default CUDA version in {self.name}"
            )
            return filter_major_minor(nvcomp_cuda_version)

        # default CUDA version from external CUDA
        if get_software_version("CUDA"):
            # Determine the CUDA version by parsing the output of nvcc. We cannot rely on the
            # module name because sites can customize these version numbers (e.g. omit the minor
            # and patch version, or choose something like 'default').
            # The search string "Cuda compilation tools" exists since at least CUDA v10.0:
            # Examples:
            # "Cuda compilation tools, release 11.4, V11.4.152"
            # "Cuda compilation tools, release 13.0, V13.0.48"
            nvcc_cuda_version_regex = re.compile(r'Cuda.*release\s([0-9]+\.[0-9]+),', re.M)
            nvcc_version_cmd = run_shell_cmd("$EBROOTCUDA/bin/nvcc --version")
            nvcc_cuda_version = nvcc_cuda_version_regex.search(nvcc_version_cmd.output)
            if nvcc_cuda_version is None:
                raise EasyBuildError("Could not extract CUDA version from nvcc: %s", nvcc_version_cmd.output)
            external_cuda_version = nvcc_cuda_version.group(1)

            if supported_cuda_versions and external_cuda_version not in supported_cuda_versions:
                # we cannot error out here to avoid breaking existing easyconfigs
                print_warning(
                    f"CUDA version '{external_cuda_version}' from external CUDA might not be supported by "
                    f"{self.name}-{self.version}: {supported_cuda_commasep}"
                )
            self.log.info(
                f"Using version '{external_cuda_version}' of loaded CUDA dependency "
                f"as default CUDA version in {self.name}"
            )
            return filter_major_minor(external_cuda_version)

        # default CUDA version set in configuration
        default_cuda_version = self.cfg['default_cuda_version']
        if default_cuda_version is not None:
            if supported_cuda_versions and default_cuda_version not in supported_cuda_versions:
                raise EasyBuildError(
                    f"Selected default CUDA version '{default_cuda_version}' not supported by "
                    f"{self.name}-{self.version}: {supported_cuda_commasep}"
                )
            return filter_major_minor(default_cuda_version)

        # default CUDA version undefined, pick one if obvious
        if len(supported_cuda_versions) == 1:
            active_cuda_version = supported_cuda_versions[0]
            self.log.info(
                f"Missing 'default_cuda_version' or CUDA dependency. Using CUDA version '{active_cuda_version}', "
                f"as it is the only version supported by {self.name}-{self.version}."
            )
            return filter_major_minor(active_cuda_version)

        error_msg = f"Missing 'default_cuda_version' and nvidia-compilers or CUDA dependency for {self.name}. "
        error_msg += "Either add nvidia-compilers or CUDA as dependency, or manually define 'default_cuda_version'."
        error_msg += "You can edit the easyconfig file, "
        error_msg += "or use 'eb --try-amend=default_cuda_version=<version>'."
        raise EasyBuildError(error_msg)

    def _get_default_compute_capability(self):
        """
        Return list of suitable CUDA compute capabilities for this installation
        Preference order:
        1. CC set by nvidia-compilers
        2. CC set by option 'cuda_compute_capabilities'
        3. CC set by easyconfig parameter 'cuda_compute_capabilities'
        """
        # CUDA compute capability from environment (e.g. defined by nvidia-compilers)
        nvcomp_cuda_cc = os.getenv('EBNVHPCCUDACC', None)
        if nvcomp_cuda_cc:
            nvcomp_cuda_cc = nvcomp_cuda_cc.split(',')
        # CUDA compute capability defined by easyconfig/cli
        cfg_compute_capability = self.cfg['cuda_compute_capabilities']
        opt_compute_capability = build_option('cuda_compute_capabilities')
        user_cuda_cc = opt_compute_capability if opt_compute_capability else cfg_compute_capability
        if user_cuda_cc and isinstance(user_cuda_cc, str):
            user_cuda_cc = [user_cuda_cc]  # keep compatibility with pre-nvidia-compilers NVHPC easyconfigs

        if nvcomp_cuda_cc and user_cuda_cc and nvcomp_cuda_cc != user_cuda_cc:
            raise EasyBuildError(
                f"Given CUDA compute capabilities {user_cuda_cc} in {self.name}-{self.version} "
                f"do not match those set by the NVHPC toolchain {nvcomp_cuda_cc}"
            )

        default_compute_capability = user_cuda_cc
        if nvcomp_cuda_cc:
            default_compute_capability = nvcomp_cuda_cc

        if default_compute_capability:
            self.log.info(f"CUDA compute capabilities used by default in NVHPC: '{default_compute_capability}'")

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

        # Own MPI: enable Nvidia HPC-X
        # replicate the environment generated by module file: "$NVHPC/comm_libs/<cuda>/hpcx/latest/modulefiles/hpcx"
        if self.cfg['module_nvhpc_own_mpi']:
            mpi_basedir = os.path.join(self.install_subdir, "comm_libs", "mpi")
            hpcx_dir = os.path.join(self.install_subdir, "comm_libs", self.active_cuda_version, 'hpcx', 'latest')
            hpcx_abs_dir = os.path.join(self.installdir, hpcx_dir)

            hpcx_environment_vars = {
                "HPCX_DIR": hpcx_abs_dir,
                "HPCX_HOME": hpcx_abs_dir,
                "HPCX_UCX_DIR": os.path.join(hpcx_abs_dir, "ucx"),
                "HPCX_UCC_DIR": os.path.join(hpcx_abs_dir, "ucc"),
                "HPCX_SHARP_DIR": os.path.join(hpcx_abs_dir, "sharp"),
                "HPCX_HCOLL_DIR": os.path.join(hpcx_abs_dir, "hcoll"),
                "HPCX_NCCL_RDMA_SHARP_PLUGIN_DIR": os.path.join(hpcx_abs_dir, "nccl_rdma_sharp_plugin"),
                "HPCX_CLUSTERKIT_DIR": os.path.join(hpcx_abs_dir, "clusterkit"),
                "HPCX_MPI_DIR": os.path.join(hpcx_abs_dir, "ompi"),
                "HPCX_OSHMEM_DIR": os.path.join(hpcx_abs_dir, "ompi"),
                "HPCX_MPI_TESTS_DIR": os.path.join(hpcx_abs_dir, "ompi", "tests"),
                "HPCX_OSU_DIR": os.path.join(hpcx_abs_dir, "ompi", "tests", "osu-micro-benchmarks"),
                "HPCX_OSU_CUDA_DIR": os.path.join(hpcx_abs_dir, "ompi", "tests", "osu-micro-benchmarks-cuda"),
            }
            self.cfg.update('modextravars', hpcx_environment_vars)
            mpi_runtime_vars = {
                "OPAL_PREFIX": os.path.join(hpcx_abs_dir, "ompi"),
                "OMPI_HOME": os.path.join(hpcx_abs_dir, "ompi"),
                "MPI_HOME": os.path.join(hpcx_abs_dir, "ompi"),
                "OSHMEM_HOME": os.path.join(hpcx_abs_dir, "ompi"),
                "SHMEM_HOME": os.path.join(hpcx_abs_dir, "ompi"),
            }
            self.cfg.update('modextravars', mpi_runtime_vars)

            self.module_load_environment.PATH.extend([
                os.path.join(mpi_basedir, 'bin'),
                os.path.join(hpcx_dir, "ucx", "bin"),
                os.path.join(hpcx_dir, "ucc", "bin"),
                os.path.join(hpcx_dir, "hcoll", "bin"),
                os.path.join(hpcx_dir, "sharp", "bin"),
                os.path.join(hpcx_dir, "ompi", "tests", "imb"),
                os.path.join(hpcx_dir, "clusterkit", "bin"),
            ])
            self.module_load_environment.LD_LIBRARY_PATH.extend([
                os.path.join(hpcx_dir, "ompi", "lib"),
                os.path.join(hpcx_dir, "ucx", "lib"),
                os.path.join(hpcx_dir, "ucx", "lib", "ucx"),
                os.path.join(hpcx_dir, "ucc", "lib"),
                os.path.join(hpcx_dir, "ucc", "lib", "ucc"),
                os.path.join(hpcx_dir, "hcoll", "lib"),
                os.path.join(hpcx_dir, "sharp", "lib"),
                os.path.join(hpcx_dir, "nccl_rdma_sharp_plugin", "lib"),
            ])
            self.module_load_environment.LIBRARY_PATH.extend([
                os.path.join(hpcx_dir, "ompi", "lib"),
                os.path.join(hpcx_dir, "ucx", "lib"),
                os.path.join(hpcx_dir, "ucc", "lib"),
                os.path.join(hpcx_dir, "hcoll", "lib"),
                os.path.join(hpcx_dir, "sharp", "lib"),
                os.path.join(hpcx_dir, "nccl_rdma_sharp_plugin", "lib"),
            ])
            for cpp_header in self.module_load_environment.alias(MODULE_LOAD_ENV_HEADERS):
                cpp_header.extend([
                    os.path.join(hpcx_dir, "ompi", "include"),
                    os.path.join(hpcx_dir, "hcoll", "include"),
                    os.path.join(hpcx_dir, "sharp", "include"),
                    os.path.join(hpcx_dir, "ucx", "include"),
                    os.path.join(hpcx_dir, "ucc", "include"),
                    os.path.join(hpcx_dir, "ompi", "include"),
                ])
            self.module_load_environment.PKG_CONFIG_PATH.extend([
                os.path.join(hpcx_dir, "hcoll", "lib", "pkgconfig"),
                os.path.join(hpcx_dir, "sharp", "lib", "pkgconfig"),
                os.path.join(hpcx_dir, "ucx", "lib", "pkgconfig"),
                os.path.join(hpcx_dir, "ompi", "lib", "pkgconfig"),
            ])

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
                                                  self.active_cuda_version)
                    self.cfg.update('modextravars', {'NVCOMPILER_COMM_LIBS_HOME': comm_libs_home})

        # In the end, set LIBRARY_PATH equal to LD_LIBRARY_PATH
        self.module_load_environment.LIBRARY_PATH = self.module_load_environment.LD_LIBRARY_PATH

    def __init__(self, *args, **kwargs):
        """Easyblock constructor, define custom class variables specific to NVHPC."""
        super().__init__(*args, **kwargs)

        host_cpu_arch = get_cpu_architecture()
        if host_cpu_arch == X86_64:
            nv_arch_tag = 'x86_64'
        elif host_cpu_arch == AARCH64:
            nv_arch_tag = 'aarch64'
        else:
            raise EasyBuildError("Unsupported CPU architecture for {self.name}-{self.version}: {host_arch_tag}")

        nv_sys_tag = f'Linux_{nv_arch_tag}'
        self.install_subdir = os.path.join(nv_sys_tag, self.version)

        self.active_cuda_version = None
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

        self.active_cuda_version = self._get_active_cuda()
        self.cfg.update('modextravars', {'EBNVHPCCUDAVER': self.active_cuda_version})

        self.default_compute_capability = self._get_default_compute_capability()
        if self.default_compute_capability:
            ebnvhpc_cudacc_var = ','.join(self.default_compute_capability)
            self.cfg.update('modextravars', {'EBNVHPCCUDACC': ebnvhpc_cudacc_var})

        self.cfg.update('modextravars', {'NVHPC': self.installdir})

        self._update_nvhpc_environment()

    def install_step(self):
        """Install by running install command."""

        # EULA for NVHPC must be accepted via --accept-eula-for EasyBuild configuration option,
        # or via 'accept_eula = True' in easyconfig file
        self.check_accepted_eula(more_info='https://docs.nvidia.com/hpc-sdk/eula/index.html', name="NVHPC")

        nvhpc_env_vars = {
            'NVHPC_INSTALL_DIR': self.installdir,
            'NVHPC_SILENT': 'true',
            'NVHPC_DEFAULT_CUDA': str(self.active_cuda_version),  # e.g. 10.2, 11.0
            }
        # NVHPC can set single valued CUDA compute capabilities as default
        if len(self.default_compute_capability) == 1:
            nvhpc_env_vars.update({
                # NVHPC_STDPAR_CUDACC uses single value CC without dot-divider (e.g. 70, 80)
                'NVHPC_STDPAR_CUDACC': self.default_compute_capability[0].replace('.', ''),
            })

        # Before installing, make sure that NVHPC chooses the CUDA version we desire
        # By default, NVHPC calls 'nvc -printcudaversion', which completely ignores our set
        # version, and only cares about the supported GPUs and found CUDA driver.
        # On a system without GPUs, this may return an incompatible CUDA version to the one
        # we define in active_cuda_version.
        desired_cuda_version = self.cfg['default_cuda_version'] or self.active_cuda_version
        desired_cuda_var_regex = [(r'DESIREDCUDA=\$(.*)', f'DESIREDCUDA={str(desired_cuda_version)}')]
        apply_regex_substitutions('./install_components/install', desired_cuda_var_regex,
                                  on_missing_match='error')

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
                    remove(path)

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
            remove([dir_path for dir_glob in mpi_dir_globs for dir_path in glob(dir_glob)])
            remove(glob(os.path.join(abs_install_subdir, 'comm_libs',  'mpi')))
        if not self.cfg['module_add_nccl']:
            nccl_dir_glob = os.path.join(abs_install_subdir, 'comm_libs', self.CUDA_VERSION_GLOB, 'nccl')
            remove(glob(nccl_dir_glob))
            if LooseVersion(self.version) >= LooseVersion('25.0'):
                remove(glob(os.path.join(abs_install_subdir, 'comm_libs',  'nccl')))
        if not self.cfg['module_add_nvshmem']:
            shmem_dir_glob = os.path.join(abs_install_subdir, 'comm_libs', self.CUDA_VERSION_GLOB, 'nvshmem')
            remove(glob(shmem_dir_glob))
            if LooseVersion(self.version) >= LooseVersion('25.0'):
                remove(glob(os.path.join(abs_install_subdir, 'comm_libs',  'nvshmem')))
        if not self.cfg['module_add_math_libs']:
            remove(glob(os.path.join(abs_install_subdir, 'math_libs')))
        if not self.cfg['module_add_profilers']:
            remove(glob(os.path.join(abs_install_subdir, 'profilers')))
        if not self.cfg['module_add_cuda']:
            # remove everything included in each cuda subdir, but leave the top CUDA dirs
            # as they are needed to determine supported versions (e.g. module-only installs)
            cuda_dir_glob = os.path.join(abs_install_subdir, 'cuda', self.CUDA_VERSION_GLOB, '*')
            remove(glob(cuda_dir_glob))
            cuda_links_glob = os.path.join(abs_install_subdir, 'cuda', '[a-z]*')
            remove(glob(cuda_links_glob))

        nvcomp_root = get_software_root("nvidia-compilers")
        if nvcomp_root:
            # link external compilers from nvidia-compilers
            current_comp_dir = os.path.join(abs_install_subdir, 'compilers')
            remove(glob(current_comp_dir))
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
        if self.cfg['module_add_nccl']:
            # Ensure that NCCL path points to correct CUDA version
            comm_lib_path = os.path.join(self.installdir, prefix, 'comm_libs')
            expected_path = resolve_path(os.path.join(comm_lib_path, str(self.active_cuda_version), 'nccl'))
            actual_path = resolve_path(os.path.join(comm_lib_path, 'nccl'))
            if actual_path != expected_path:
                raise EasyBuildError(
                    f"CUDA symlink for NCCL libraries does not match: {expected_path} != {actual_path}")
        if self.cfg['module_add_nvshmem']:
            # Ensure that NVSHMEM path points to correct CUDA version
            comm_lib_path = os.path.join(self.installdir, prefix, 'comm_libs')
            expected_path = resolve_path(os.path.join(comm_lib_path, str(self.active_cuda_version), 'nvshmem'))
            actual_path = resolve_path(os.path.join(comm_lib_path, 'nvshmem'))
            if actual_path != expected_path:
                raise EasyBuildError(
                    f"CUDA symlink for NVSHMEM libraries does not match: {expected_path} != {actual_path}")
        if self.cfg['module_add_math_libs']:
            # Ensure that math_libs path points to correct CUDA version
            math_lib_path = os.path.join(self.installdir, prefix, 'math_libs')
            expected_path = resolve_path(os.path.join(math_lib_path, str(self.active_cuda_version), 'include'))
            actual_path = resolve_path(os.path.join(math_lib_path, 'include'))
            if actual_path != expected_path:
                raise EasyBuildError(
                    f"CUDA symlink for math libraries does not match: {expected_path} != {actual_path}")
            nvhpc_files.extend([
                os.path.join(prefix, 'math_libs', 'lib64', f'libcublas.{shlib_ext}'),
                os.path.join(prefix, 'math_libs', 'lib64', f'libcufftw.{shlib_ext}'),
                os.path.join(prefix, 'math_libs', 'include', 'cublas.h'),
                os.path.join(prefix, 'math_libs', 'include', 'cufftw.h'),
            ])
        if self.cfg['module_add_cuda']:
            nvhpc_files.extend([
                os.path.join(prefix, 'cuda', self.active_cuda_version, 'bin', 'cuda-gdb'),
                os.path.join(prefix, 'cuda', self.active_cuda_version, 'lib64', f'libcudart.{shlib_ext}'),
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
            hpcx_dir = os.path.join(self.installdir, prefix, 'comm_libs', self.active_cuda_version, 'hpcx')
            mpi_hello_src = os.path.join(hpcx_dir, 'latest', 'ompi', 'tests', 'examples', 'hello_c.c')
            mpi_hello_exe = os.path.join(tmpdir, 'mpi_test_' + os.path.splitext(os.path.basename(mpi_hello_src))[0])
            self.log.info("Adding minimal MPI test program to sanity checks: %s", mpi_hello_exe)
            custom_commands.append(f"mpicc {mpi_hello_src} -o {mpi_hello_exe}")

            # Run MPI test binary
            mpi_cmd_tmpl, params = get_mpi_cmd_template(toolchain.NVHPC, {}, mpi_version=self.version)
            ranks = min(8, self.cfg.parallel)
            params.update({'nr_ranks': ranks, 'cmd': mpi_hello_exe})

            mpi_cmd = ' && '.join([
                # allow oversubscription of MPI ranks to cores
                "export OMPI_MCA_rmaps_base_oversubscribe=true",
                # workaround for problem with core binding with OpenMPI 4.x,
                # errors like: hwloc_set_cpubind returned "Error" for bitmap "0"
                # see https://github.com/open-mpi/ompi/issues/12470
                "export OMPI_MCA_hwloc_base_binding_policy=none",
                mpi_cmd_tmpl % params,
            ])
            custom_commands.append(mpi_cmd)

        super().sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
